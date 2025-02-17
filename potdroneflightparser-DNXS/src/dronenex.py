# Dronenex.py - Based on main.py by Koen Aerts and Rob Pritt from PotDroneFlightParser
# Part of Jacob Williams' Dronenex.us project
# Re-implements functionality from main.py, but designed to run headless and automatically process Zipped Potensic logs into KML files as they are moved into a directory

#!/usr/bin/env python3
import os
import time
import re
import logging
import shutil
from pathlib import Path
# Needed to automatically detect new files
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from zipfile import ZipFile
import datetime
import glob

# Import existing functionality from PotDroneFlightParser
from parser import AtomBaseLogParser, DreamerBaseLogParser # for parsing flight data
from exports import ExportKml # Conversion to KML file
from headless_common import Common # utility functions
from enums import DroneStatus, FlightMode # status definitions
from db import Db # sqlite database support

# Set up logging to both file and console
logging.basicConfig(
    level=logging.DEBUG,  # debug level shows all messages
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('flight_processor.log'), # saves log to file
        logging.StreamHandler() # shows log in console
    ]
)

# Add translation function to global namespace, used by parser for error messages
import builtins
builtins._ = lambda x: x

# Processor class that handles monitoring directories, managing processing pipeline, database operations and file management
class FlightLogProcessor:
    def __init__(self, input_dir: str, output_dir: str): # Initialize processor, input/output directories
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.common = Common(None) # Utility functions, no GUI needed
        self._db = Db(os.path.join(self.input_dir, "FlightLogData.db")) # Initilaize database in input directory (for now)
        self.ensure_directories() # Creates required directories (if they do not exist)
        self.temp_dir = "/tmp/flightdata" # Temporary directory for ZIP extraction

        # Initialize attributes that parser expects
        self.logdata = [] # parsed flight data
        self.zipFilename = None # Current .ZIP being processed
        self.pathCoords = [] # Flight path coordinates
        self.flightStarts = {} # Start point of each flight
        self.flightEnds = {} # End point of each flight
        self.flightStats = [] # Statistics for each flight
        self.flightOptions = [] # Available flight numbers

    def ensure_directories(self):
        # Create input and output directories if they do not exist.
        Path(self.input_dir).mkdir(parents=True, exist_ok=True)
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def initiate_import_file(self, selected_file):
        # Replicates the initiate_import_file method from main.py
        if not os.path.isfile(selected_file):
            logging.error(f"No valid file specified: {selected_file}")
            return

        # Extracts date and model from filename
        zip_basename = os.path.basename(selected_file)
        drone_model = re.sub(r"[0-9]*-(.*)-Drone.*", r"\1", zip_basename)
        drone_model = re.sub(r"[^\w]", r" ", drone_model)
        lcDM = drone_model.lower()

        # Only process atom/p1a drone files
        if 'p1a' in lcDM or 'atom' in lcDM:
            # Check if already imported
            already_imported = self._db.execute("SELECT importedon FROM imports WHERE importref = ?", (zip_basename,))
            if already_imported is None or len(already_imported) == 0:
                logging.info(f"Starting import of {zip_basename}")
                self.import_file(drone_model, zip_basename, selected_file)
            else:
                logging.warning(f"File already imported on {already_imported[0][0]}")

    def import_file(self, drone_model, zip_basename, selected_file):
        # Replicates the import_file method from main.py
        logging.info(f"Importing {zip_basename} for model {drone_model}")
        hasFc = False # Flag to track if we found any flight control files
        lcDM = drone_model.lower()
        fpvList = [] # List to collect FPV files

        # Clean and recreate temporary directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)

        # Extract Zip contents
        with ZipFile(selected_file, 'r') as unzip:
            logging.info(f"ZIP contents: {unzip.namelist()}")
            unzip.extractall(path=self.temp_dir)

        # Process each file in the ZIP
        for binFile in glob.glob(os.path.join(self.temp_dir, '**/*'), recursive=True):
            binBaseName = os.path.basename(binFile)
            logging.debug(f"Processing file: {binBaseName}")

            # Determine file type based on extraction
            binType = "FPV" if binBaseName.endswith("-FPV.bin") else (
                "BIN" if binBaseName.endswith("-FC.bin") else (
                    "FC" if binBaseName.endswith("-FC.fc") else None))

            if binType is not None:
                if binType == 'FPV':
                    # Collect FPV files for later processing
                    fpvList.append(binFile)
                else:
                    # Handles flight control files (FC.bin or FC.fc)
                    if not hasFc:
                        # First FC file found, setup database entries
                        logDate = re.sub(r"-.*", r"", zip_basename)
                        logging.info(f"Adding model {drone_model} to database")

                        # add drone model if new
                        self._db.execute("INSERT OR IGNORE INTO models(modelref) VALUES(?)", (drone_model,))

                        # Record this import
                        self._db.execute(
                            "INSERT OR IGNORE INTO imports(importref, modelref, dateref, importedon) VALUES(?,?,?,?)",
                            (zip_basename, drone_model, logDate, datetime.datetime.now().isoformat())
                        )
                        hasFc = True

                    # Copy FC file ti working directory
                    dest_path = os.path.join(self.logfileDir, binBaseName)
                    logging.info(f"Copying {binBaseName} to {dest_path}")
                    shutil.copyfile(binFile, dest_path)

                    # Record file in database
                    self._db.execute(
                        "INSERT INTO log_files(filename, importref, bintype) VALUES(?,?,?)",
                        (binBaseName, zip_basename, binType)
                    )

        if hasFc:
            # Process FPV files after FC files
            for fpvFile in fpvList:
                fpvBaseName = os.path.basename(fpvFile)
                logging.info(f"Copying FPV file {fpvBaseName}")
                shutil.copyfile(fpvFile, os.path.join(self.logfileDir, fpvBaseName))
                self._db.execute(
                    "INSERT INTO log_files(filename, importref, bintype) VALUES(?,?,?)",
                    (fpvBaseName, zip_basename, "FPV")
                )

            logging.info("Log import completed")

            # Reset necessary attributes before additional parsing
            self.logdata = []
            self.zipFilename = zip_basename
            self.pathCoords = []
            self.flightStarts = {}
            self.flightEnds = {}
            self.flightStats = []
            self.flightOptions = []

            # Parse the data (depending on drone type)
            if ('p1a' in lcDM):
                logging.info("Creating P1A parser")
                parser = DreamerBaseLogParser(self)
            else:
                logging.info("Creating Atom parser")
                parser = AtomBaseLogParser(self)

            # Parse the flight data
            logging.info(f"Starting parse of {zip_basename}")
            parser.parse(zip_basename)
            logging.info(f"Parse completed. Found {len(self.logdata)} records")

            if self.logdata:
                # If it gets flight data, export to KML
                kml_filename = re.sub(r"\.zip$", "", zip_basename) + ".kml"
                kml_path = os.path.join(self.output_dir, kml_filename)
                logging.info(f"Creating KML file: {kml_path}")

                # Create KML export with flight data
                kml = ExportKml(
                    commonlib=self.common,
                    columnnames=self.columns,
                    rows=self.logdata,
                    name=f"{drone_model} Flight Log",
                    description=f"Flight log from {logDate}",
                    pathcolor="#ff0000", # red flight path
                    pathwidth="3.0", # line width
                    homecolorref="1", # home point marker color
                    ctrlcolorref="1", # controller marker color
                    dronecolorref="1", # drone marker color
                    flightstarts=self.flightStarts,
                    flightends=self.flightEnds,
                    flightstats=self.flightStats,
                    uom="metric"
                )
                kml.save(kml_path)
                logging.info(f"Created KML file: {kml_path}")
            else:
                logging.warning(f"No flight data found in {zip_basename}")

        else:
            logging.warning("Nothing to import - no FC files found")

        # Clean up temporary files
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def process_zip_file(self, zip_path: str):
        # Main entry point for processing a new ZIP file, with error handling
        try:
            self.initiate_import_file(zip_path)
        except Exception as e:
            logging.error(f"Error processing {zip_path}: {e}", exc_info=True)

    # Properties and methods needed by the parser
    @property
    def logfileDir(self):
        return self.input_dir

    @property
    def db(self):
        return self._db

    def show_warning_message(self, message):
        logging.warning(message)

    def show_error_message(self, message):
        logging.error(message)

    def show_info_message(self, message):
        logging.info(message)

    @property
    def columns(self):
        # Define the columns that exist in the binary flight data, read from binary FC files, used to create KML file
        return (
        'recnum', 'recid', 'flight', 'timestamp', 'tod', 'time', 'distance1', 'dist1lat', 'dist1lon', 'distance2',
        'dist2lat', 'dist2lon', 'distance3', 'altitude1', 'altitude2', 'altitude2metric', 'speed1', 'speed1lat',
        'speed1lon', 'speed2', 'speed2lat', 'speed2lon', 'speed1vert', 'speed2vert', 'satellites', 'ctrllat',
        'ctrllon', 'homelat', 'homelon', 'dronelat', 'dronelon', 'orientation1', 'orientation2', 'roll',
        'winddirection', 'motor1status', 'motor2status', 'motor3status', 'motor4status', 'motorstatus',
        'dronestatus', 'droneaction', 'rssi', 'channel', 'flightctrlconnected', 'remoteconnected',
        'droneconnected', 'rth', 'positionmode', 'gps', 'inuse', 'traveled', 'batterylevel', 'batterytemp',
        'batterycurrent', 'batteryvoltage', 'batteryvoltage1', 'batteryvoltage2', 'flightmode', 'flightcounter')


class LogFileHandler(FileSystemEventHandler):
    # Watches for new files in input directory, inherits from FileSystemEventHandler to receive file system events
    def __init__(self, processor: FlightLogProcessor):
        self.processor = processor

    def on_created(self, event):
        # Called when a new file is created in watched directory
        if event.is_directory:
            return
        if event.src_path.lower().endswith('.zip'):
            logging.info(f"New file detected: {event.src_path}")
            # Wait a moment to ensure file is completely written
            time.sleep(1)
            self.processor.process_zip_file(event.src_path)


def main():
    # main program entry point
    # Sets up the file monitoring and runs the main loop
    input_dir = "/home/jake/uploads"
    output_dir = "/home/jake/kml-viewer/public"

    # Create processor and file watcher
    processor = FlightLogProcessor(input_dir, output_dir)
    event_handler = LogFileHandler(processor)
    observer = Observer()
    observer.schedule(event_handler, input_dir, recursive=False)
    observer.start()

    logging.info(f"Started monitoring {input_dir} for new flight log files")
    logging.info(f"KML files will be exported to {output_dir}")

    try:
        # Process any existing zip files first
        existing_files = list(Path(input_dir).glob('*.zip'))
        if existing_files:
            logging.info(f"Found {len(existing_files)} existing ZIP files to process")
            for zip_file in existing_files:
                processor.process_zip_file(str(zip_file))

        # Then keep running to watch for new files
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logging.info("\nStopping file monitor...")

    observer.join()


if __name__ == "__main__":
    main()