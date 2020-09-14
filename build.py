import os
from os.path import isdir, join, abspath, dirname, relpath, isfile, splitext
import sys
import logging
import shutil
import glob
import re
import zipfile
import subprocess
import json
import argparse

ROOT_DIR = abspath(dirname(__file__))
BUILD_DIR = join(dirname(__file__), "build")
LOG_FILENAME = "build.log"
FILE_LOG_FORMAT = "[%(asctime)s][%(name)s][%(levelname)s]: %(message)s"
CONSOLE_LOG_FORMAT = "[%(name)s][%(levelname)s]: %(message)s"
DATE_FORMAT = "%Y-%b-%d %H:%M:%S"
LOG_LEVEL = logging.DEBUG
REVISION_DIR = BUILD_DIR
REVISION_FILENAME = "revision.txt"
REVISION_PATH = join(BUILD_DIR, REVISION_FILENAME)
MOD_DIR = join(ROOT_DIR, "mods")
BIN_DIR = join(ROOT_DIR, "bin")

class BuildStep:
    _ID = 0
    def __init__(self, logger, name=None, stop_on_fail=True):
        self.name = name
        self.result = False
        self._logger = logger
        self._stop_on_fail = stop_on_fail
        if name is None:
            self.name = "BuildStep_{:02}".format(BuildStep._ID)
            BuildStep._ID += 1
    
    def execute(self):
        pass
        
class GenericBuildStep(BuildStep):
    def __init__(self, logger, callback, name=None, stop_on_fail=True):
        super().__init__(logger, name=name, stop_on_fail=stop_on_fail)
        self.execute = callback
        
class CommandLineBuildStep(BuildStep):
    def __init__(self, logger, command, name=None, stop_on_fail=True):
        super().__init__(logger, name=name, stop_on_fail=stop_on_fail)
        self.command = command
            
    def execute(self):
        self._logger.info("Executing build step: {}".format(self.name))
        self.result = os.system(self.command)
        if self.result != 0 and self._stop_on_fail:
            raise RuntimeError("The build step failed with error code: {}".format(self.result))
        self._logger.info("Completed build step: {}".format(self.name))   
        
class CopyFilesBuildStep(BuildStep):
    def __init__(self, logger, source_dir, dest_dir, create_dest_dir=True, recursive=False, regex=".*", name=None, stop_on_fail=True):
        super().__init__(logger, name=name, stop_on_fail=stop_on_fail)
        self.source_dir = source_dir
        self.dest_dir = dest_dir
        self.create_dest_dir = create_dest_dir
        self.recursive = recursive
        self.regex = regex
    
    def execute(self):
        if not isdir(self.dest_dir):
            if self.create_dest_dir:
                self._logger.info("Creating destination directory: {}".format(self.dest_dir))
                os.makedirs(self.dest_dir)
            else:
                raise FileNotFoundError("Destination does not exist: {}".format(self.dest_dir))
            
        self._logger.info("Copying files from {} to {}".format(self.source_dir, self.dest_dir))
        matches = []
        for root, dirnames, filenames in os.walk(self.source_dir):
            for filename in filenames:
                if re.search(self.regex, filename, flags=re.IGNORECASE):
                    matches.append(os.path.join(root, filename))
            if not self.recursive:
                break
                
        for file in matches:
            dest_filename = join(self.dest_dir, relpath(file, start=self.source_dir))
            self._logger.info("Copying {} to {}".format(file, dest_filename))
            if not isdir(dirname(dest_filename)):
                os.makedirs(dirname(dest_filename))
            shutil.copy2(file, dest_filename)

            
class DeleteFilesBuildStep(BuildStep):
    def __init__(self, logger, directory, regex="*", recursive=False, name=None, stop_on_fail=True):
        super().__init__(logger, name=name, stop_on_fail=stop_on_fail)
        self.directory = directory
        self.regex = regex
        self.recursive = recursive
        
    def execute(self):
        relative_path = relpath(self.directory)
    
        # Guard against deleting files in directories which are not subdirectories.
        if ".." in relative_path:
            raise ValueError("The path must be a subdirectory of the current directory")
        
        self._logger.info("Deleting files in directory: {}".format(self.directory))
        matches = []
        dir_matches = []
        for root, dirnames, filenames in os.walk(self.directory):
            for filename in filenames:
                if re.search(self.regex, filename, flags=re.IGNORECASE):
                    matches.append(os.path.join(root, filename))
            for dir in dirnames:
                if re.search(self.regex, dir, flags=re.IGNORECASE):
                    dir_matches.append(os.path.join(root, dir))
            if not self.recursive:
                break
                
        for file in matches:
            self._logger.info("Deleting file {}".format(file))
            os.remove(file)
                
        for dir in dir_matches:
            self._logger.info("Deleting directory {}".format(dir))
            shutil.rmtree(dir)  

            
class RenameFileBuildStep(BuildStep):
    def __init__(self, logger, source_dir, dest_filename , create_dest_dir=True, regex=".*", name=None, stop_on_fail=True):
        super().__init__(logger, name=name, stop_on_fail=stop_on_fail)
        self.source_dir = source_dir
        self.dest_filename = dest_filename
        self.create_dest_dir = create_dest_dir
        self.regex = regex
    
    def execute(self):
        if not isdir(dirname(self.dest_filename)):
            if self.create_dest_dir:
                self._logger.info("Creating destination directory: {}".format(dirname(self.dest_filename)))
                os.makedirs(dirname(dirname(self.dest_filename)))
            else:
                raise FileNotFoundError("Destination does not exist: {}".format(dirname(self.dest_filename)))
        source_file = None
        for root, dirnames, filenames in os.walk(self.source_dir):
            for filename in filenames:
                if re.search(self.regex, filename, flags=re.IGNORECASE):
                    source_file = os.path.join(root, filename)
        if source_file is None:
            raise FileNotFoundError("Failed to find a file matching the regex \"{}\"".format(self.regex))
        self._logger.info("Renaming {} to {}".format(source_file, self.dest_filename))
        shutil.move(source_file, self.dest_filename)
        
 
class ExtractFilesBuildStep(BuildStep):
    def __init__(self, logger, zip_file, dest_dir, create_dest_dir=True, name=None, stop_on_fail=True):
        super().__init__(logger, name=name, stop_on_fail=stop_on_fail)
        self.zip_file = zip_file
        self.dest_dir = dest_dir
        self.create_dest_dir = create_dest_dir
        
    def execute(self):
        if not isdir(self.dest_dir):
            if self.create_dest_dir:
                self._logger.info("Creating destination directory: {}".format(self.dest_dir))
                os.makedirs(self.dest_dir)
            else:
                raise FileNotFoundError("Destination does not exist: {}".format(self.dest_dir))
                
        self._logger.info("Extracting {} to {}".format(self.zip_file, self.dest_dir))
        with zipfile.ZipFile(self.zip_file,"r") as z:
            z.extractall(self.dest_dir)
 
 
class ZipFilesBuildStep(BuildStep):
    def __init__(self, logger, zip_file, source_dir, dest_dir, root, relative_path=None, create_dest_dir=True, recursive=False, regex=".*", name=None, stop_on_fail=True, mode="w"):
        super().__init__(logger, name=name, stop_on_fail=stop_on_fail)
        self.zip_file = zip_file
        self.source_dir = source_dir
        self.dest_dir = dest_dir
        self.root = root
        self.create_dest_dir = create_dest_dir
        self.regex = regex
        self.recursive = recursive
        self.mode = mode
        self.relative_path = relative_path
        
    def execute(self):
        if not isdir(self.dest_dir):
            if self.create_dest_dir:
                self._logger.info("Creating destination directory: {}".format(self.dest_dir))
                os.makedirs(self.dest_dir)
            else:
                raise FileNotFoundError("Destination does not exist: {}".format(self.dest_dir))
                
        self._logger.info("Collecting files from {}".format(self.source_dir))
        matches = []
        for root, dirnames, filenames in os.walk(self.source_dir):
            for filename in filenames:
                filename = relpath(join(root, filename), start=self.root)
                if re.search(self.regex, filename, flags=re.IGNORECASE):
                    self._logger.debug("Found match: {}".format(filename))
                    matches.append(filename)
            if not self.recursive:
                break
                
        full_zip_filename = join(self.dest_dir, self.zip_file)
        self._logger.info("Creating zip file: {}".format(full_zip_filename))
        with zipfile.ZipFile(full_zip_filename, self.mode, zipfile.ZIP_DEFLATED) as z:
            for file in matches:
                dest_filename = relpath(file, start=self.root)
                arc_name = None
                if self.relative_path is not None:
                    arc_name = relpath(file, self.relative_path)
                self._logger.info("   Zipping {}".format(dest_filename))
                z.write(dest_filename, arcname=arc_name)
  
  
def load_ignore_list(filename):
    ignoreList = []
    with open(filename, "r") as file:
        for line in file.readlines():
            line = line.strip()
            if line == "":
                continue
            line = line.replace("*", "__WILDCARD__")
            line = re.escape(line)
            line = line.replace("__WILDCARD__", ".*")
            ignoreList.append(line)
    return ignoreList

def create_version_file(revision):
    with open(REVISION_PATH, "w") as file:
        file.write(revision)
 
def get_mod_list(mod_dict, keys):
    mod_list = []
    for key in keys:
        mods = mod_dict[key]
        mod_list.extend(mods)
    return mod_list

 
if __name__ == "__main__":
    parser = argparse.ArgumentParser("build.py")
    parser.add_argument("--revision", type=str.lower, default="dirty")

    args = parser.parse_args(sys.argv[1:])
    revision = args.revision

    if not isdir(BUILD_DIR):
        os.makedirs(BUILD_DIR)
    log_filename = join(BUILD_DIR, LOG_FILENAME)
    logger = logging.getLogger("build")
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler_formatter = logging.Formatter(fmt=CONSOLE_LOG_FORMAT, datefmt=DATE_FORMAT)
    console_handler.setFormatter(console_handler_formatter)
    logger.addHandler(console_handler)
    file_handler = logging.FileHandler(log_filename)
    file_handler_formatter = logging.Formatter(fmt=FILE_LOG_FORMAT, datefmt=DATE_FORMAT)
    file_handler.setFormatter(file_handler_formatter)
    logger.addHandler(file_handler)
    logger.setLevel(LOG_LEVEL)
    current_directory = ROOT_DIR
    os.chdir(ROOT_DIR)
    build_steps = []
    numErrors = 0
    buildFailed = False
    
    client_package_filename = "brave-new-world-client.zip"
    server_package_filename = "brave-new-world-server.zip"
    
    # Create revision.txt file
    build_steps.append(GenericBuildStep(logger, lambda: create_version_file(revision), name="Create revision file"))
    
    # Zip into package

    # Package client
    build_steps.append(ZipFilesBuildStep(logger, client_package_filename, REVISION_DIR, BUILD_DIR, ROOT_DIR, regex=re.escape(REVISION_FILENAME), recursive=False, name="Zip revision.txt"))
    client_dir = join(ROOT_DIR, "client")
    build_steps.append(ZipFilesBuildStep(logger, client_package_filename, client_dir, BUILD_DIR, ROOT_DIR, relative_path=client_dir, recursive=True, name="Zip client", mode="a"))
    build_steps.append(ZipFilesBuildStep(logger, client_package_filename, MOD_DIR, BUILD_DIR, ROOT_DIR, recursive=True, name="Zip client mods", mode="a"))
    build_steps.append(ZipFilesBuildStep(logger, client_package_filename, BIN_DIR, BUILD_DIR, ROOT_DIR, recursive=True, name="Zip client bin", mode="a"))


    # Package server
    build_steps.append(ZipFilesBuildStep(logger, server_package_filename, REVISION_DIR, BUILD_DIR, ROOT_DIR, regex=re.escape(REVISION_FILENAME), recursive=False, name="Zip revision.txt"))
    server_dir = join(ROOT_DIR, "server")
    build_steps.append(ZipFilesBuildStep(logger, server_package_filename, server_dir, BUILD_DIR, ROOT_DIR, relative_path=server_dir, recursive=True, name="Zip server", mode="a"))
    build_steps.append(ZipFilesBuildStep(logger, server_package_filename, MOD_DIR, BUILD_DIR, ROOT_DIR, recursive=True, name="Zip server mods", mode="a"))
    build_steps.append(ZipFilesBuildStep(logger, server_package_filename, BIN_DIR, BUILD_DIR, ROOT_DIR, relative_path=BIN_DIR, recursive=True, name="Zip server bin", mode="a"))
       
    try:
        logger.info("Root directory: {}".format(ROOT_DIR))
        for build_step in build_steps:
            logger.info("Executing build step: {}".format(build_step.name))
            build_step.execute()
            if build_step.result != 0:
                numErrors += 1
                logger.error("Build step failed with error code: {}".format(build_step.result))
                if build_step.stop_on_fail:
                    buildFailed = True
                    break
            else:
                logger.info("Build step succeeded.")
    except Exception as e:
        logger.exception("Exception occurred during build step: {}".format(build_step.name))
        exit(1)
    
    status = "failed" if buildFailed else "succeeded"
    logger.info("Build {} with {} errors.".format(status, numErrors))
    if buildFailed:
        exit(1)
    exit(0)
    
    
        
    
        
