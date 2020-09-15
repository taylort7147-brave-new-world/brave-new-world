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
BUILD_DIR = join(ROOT_DIR, "build")
LOG_DIR = join(ROOT_DIR, "logs")
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

class CleanBuildStep(BuildStep):
    def __init__(self, logger, dir_, **kwargs):
        super().__init__(logger, **kwargs)
        self.dir = dir_

    def execute(self):
        if not isdir(self.dir):
            raise FileNotFoundError(f"Directory does not exist: {self.dir}")
        for filename in os.listdir(self.dir):
            file_path = join(self.dir, filename)
            self._logger.info(f"Deleting {file_path}")
            if isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif isdir(file_path):
                shutil.rmtree(file_path)


class CopyFilesBuildStep(BuildStep):
    def __init__(self, logger, root, files, dest_dir, create_dest_dir=True, name=None, stop_on_fail=True):
        super().__init__(logger, name=name, stop_on_fail=stop_on_fail)
        self.files = files
        self.dest_dir = dest_dir
        self.create_dest_dir = create_dest_dir
        self.root = root
    
    def execute(self):
        copy_count = 0
        if not isdir(self.dest_dir):
            if self.create_dest_dir:
                self._logger.info("Creating destination directory: {}".format(self.dest_dir))
                os.makedirs(self.dest_dir)
            else:
                raise FileNotFoundError("Destination does not exist: {}".format(self.dest_dir))
            
        for file in self.files:
            dest_filename = join(self.dest_dir, relpath(file, start=self.root))
            self._logger.info("Copying {} to {}".format(file, dest_filename))
            if not isdir(dirname(dest_filename)):
                os.makedirs(dirname(dest_filename))
            shutil.copy2(file, dest_filename)
            copy_count += 1
        self._logger.info(f"Copied {copy_count} files")

  
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

    if not isdir(LOG_DIR):
        os.makedirs(LOG_DIR)

    log_filename = join(LOG_DIR, LOG_FILENAME)
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
    
    # Clean
    build_steps.append(CleanBuildStep(logger, BUILD_DIR, name="Clean build directory"))
    
    # Create revision.txt file
    build_steps.append(GenericBuildStep(logger, lambda: create_version_file(revision), name="Create revision file"))
    
    bin_files = glob.glob(join(BIN_DIR, "*.*"))
    mod_files = glob.glob(join(MOD_DIR, "*.*"))
    client_files = glob.glob(join(ROOT_DIR, "client", "**/*.*"))
    server_files = glob.glob(join(ROOT_DIR, "server", "**/*.*"))
    revision_files = [join(REVISION_DIR, REVISION_FILENAME)]

    client_dir = join(ROOT_DIR, "client")
    server_dir = join(ROOT_DIR, "server")

    client_package_dir = join(BUILD_DIR, "client")
    server_package_dir = join(BUILD_DIR, "server")

    # Package client
    build_steps.append(CopyFilesBuildStep(logger, REVISION_DIR, revision_files, client_package_dir, name="Copy revision file"))
    build_steps.append(CopyFilesBuildStep(logger, client_dir, client_files, client_package_dir, name="Copy client"))
    build_steps.append(CopyFilesBuildStep(logger, ROOT_DIR, bin_files, client_package_dir, name="Copy bin/ to client"))
    build_steps.append(CopyFilesBuildStep(logger, ROOT_DIR, mod_files, client_package_dir, name="Copy mods/ to client"))

    # Package server
    build_steps.append(CopyFilesBuildStep(logger, REVISION_DIR, revision_files, server_package_dir, name="Copy revision file"))
    build_steps.append(CopyFilesBuildStep(logger, server_dir, server_files, server_package_dir, name="Copy server"))
    build_steps.append(CopyFilesBuildStep(logger, BIN_DIR, bin_files, server_package_dir, name="Copy bin/ to server"))
    build_steps.append(CopyFilesBuildStep(logger, ROOT_DIR, mod_files, server_package_dir, name="Copy mods/ to server"))
       
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
    
    
        
    
        
