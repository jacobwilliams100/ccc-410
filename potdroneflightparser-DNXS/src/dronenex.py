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


from parser import AtomBaseLogParser, DreamerBaseLogParser
from exports import ExportKml
from headless_common import Common
from enums import DroneStatus, FlightMode
from db import Db

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG for more detailed logs
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('flight_processor.log'),
        logging.StreamHandler()
    ]
)

# Add translation function to global namespace
import builtins

builtins._ = lambda x: x


class FlightLogProcessor:
    def __init__(self, input_dir: str, output_dir: str):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.common = Common(None)
        self._db = Db(os.path.join(self.input_dir, "FlightLogData.db"))
        self.ensure_directories()
        self.temp_dir = "/tmp/flightdata"

        # Initialize attributes that parser expects
        self.logdata = []
        self.zipFilename = None
        self.pathCoords = []
        self.flightStarts = {}
        self.flightEnds = {}
        self.flightStats = []
        self.flightOptions = []

    def ensure_directories(self):
        """Create directories if they don't exist"""
        Path(self.input_dir).mkdir(parents=True, exist_ok=True)
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def export_individual_flights(self, zip_basename, drone_model, parser):
        """Export individual KML files for each flight using timestamp-only filenames"""
        if not self.logdata:
            logging.warning(f"No flight data found in {zip_basename}")
            return

        # Add this debug line
        logging.info(f"Full logdata has {len(self.logdata)} records")

        logging.info(f"Exporting {len(self.flightStarts)} individual flight KML files")

        # Export each flight as a separate KML file
        for flight_num in self.flightStarts.keys():
            start_idx = self.flightStarts[flight_num]
            end_idx = self.flightEnds[flight_num]

            # Add this debug line
            logging.info(f"Flight {flight_num}: records from {start_idx} to {end_idx}")

            # Get flight-specific data
            flight_data = self.logdata[start_idx:end_idx + 1]

            # Add these debug lines
            logging.info(f"Flight {flight_num}: {len(flight_data)} records")
            if len(flight_data) > 0:
                # Check first and last timestamp
                first_record = flight_data[0]
                last_record = flight_data[-1]
                timestamp_idx = self.columns.index('timestamp')

                if timestamp_idx < len(first_record) and timestamp_idx < len(last_record):
                    first_ts = first_record[timestamp_idx]
                    last_ts = last_record[timestamp_idx]
                    logging.info(f"Flight {flight_num} timestamps: first={first_ts}, last={last_ts}")
                    if first_ts == last_ts:
                        logging.warning(f"Flight {flight_num} has identical start and end timestamps!")

            flight_stats = [self.flightStats[0], self.flightStats[int(flight_num)]]

            # Extract flight-specific path coordinates
            flight_path_coords = None
            flight_num_int = int(flight_num)
            if self.pathCoords and len(self.pathCoords) > 0:
                # The flight_num is 1-indexed, while pathCoords is 0-indexed
                if flight_num_int <= len(self.pathCoords):
                    flight_path_coords = self.pathCoords[flight_num_int - 1]
                    logging.info(f"Found path coordinates for flight {flight_num}: {len(flight_path_coords)} segments")
                else:
                    logging.warning(f"No path coordinates found for flight {flight_num}")

            # Create timestamp-only filename
            if flight_data:
                # Extract timestamp from first data point
                start_timestamp = datetime.datetime.fromisoformat(
                    flight_data[0][self.columns.index('timestamp')]
                )
                # Format timestamp for filename (YYYYMMDD_HHMMSS)
                kml_filename = start_timestamp.strftime('%Y%m%d_%H%M%S.kml')
            else:
                # Fallback if no data (should never happen)
                logDate = re.sub(r"-.*", r"", zip_basename)
                kml_filename = f"{logDate}_flight{flight_num}.kml"

            kml_path = os.path.join(self.output_dir, kml_filename)

            logging.info(f"Processing flight {flight_num} with {len(flight_data)} data points")

            # Export individual flight KML
            kml = ExportKml(
                commonlib=self.common,
                columnnames=self.columns,
                rows=flight_data,
                name=f"{drone_model} Flight {flight_num}",
                description=f"Flight on {start_timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
                pathcolor="#ff0000",
                pathwidth="3.0",
                homecolorref="1",
                ctrlcolorref="1",
                dronecolorref="1",
                flightstarts={flight_num: 0},  # Adjust indices for single flight
                flightends={flight_num: len(flight_data) - 1},
                flightstats=flight_stats,
                pathCoords=flight_path_coords,
                uom="metric"
            )
            kml.save(kml_path)
            logging.info(f"Exported KML file: {kml_path}")

    def initiate_import_file(self, selected_file):
        """Replicates the initiate_import_file method from main.py"""
        if not os.path.isfile(selected_file):
            logging.error(f"No valid file specified: {selected_file}")
            return

        zip_basename = os.path.basename(selected_file)
        drone_model = re.sub(r"[0-9]*-(.*)-Drone.*", r"\1", zip_basename)
        drone_model = re.sub(r"[^\w]", r" ", drone_model)
        lcDM = drone_model.lower()

        if 'p1a' in lcDM or 'atom' in lcDM:
            already_imported = self._db.execute("SELECT importedon FROM imports WHERE importref = ?", (zip_basename,))
            if already_imported is None or len(already_imported) == 0:
                logging.info(f"Starting import of {zip_basename}")
                self.import_file(drone_model, zip_basename, selected_file)
            else:
                logging.warning(f"File already imported on {already_imported[0][0]}")

    def import_file(self, drone_model, zip_basename, selected_file):
        """Replicates the import_file method from main.py"""
        logging.info(f"Importing {zip_basename} for model {drone_model}")
        hasFc = False
        lcDM = drone_model.lower()
        fpvList = []

        # Extract the bin files and copy to the app data directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)

        with ZipFile(selected_file, 'r') as unzip:
            logging.info(f"ZIP contents: {unzip.namelist()}")
            unzip.extractall(path=self.temp_dir)

        for binFile in glob.glob(os.path.join(self.temp_dir, '**/*'), recursive=True):
            binBaseName = os.path.basename(binFile)
            logging.debug(f"Processing file: {binBaseName}")

            binType = "FPV" if binBaseName.endswith("-FPV.bin") else (
                "BIN" if binBaseName.endswith("-FC.bin") else (
                    "FC" if binBaseName.endswith("-FC.fc") else None))

            if binType is not None:
                if binType == 'FPV':
                    fpvList.append(binFile)
                else:
                    if not hasFc:
                        logDate = re.sub(r"-.*", r"", zip_basename)
                        logging.info(f"Adding model {drone_model} to database")
                        self._db.execute("INSERT OR IGNORE INTO models(modelref) VALUES(?)", (drone_model,))
                        self._db.execute(
                            "INSERT OR IGNORE INTO imports(importref, modelref, dateref, importedon) VALUES(?,?,?,?)",
                            (zip_basename, drone_model, logDate, datetime.datetime.now().isoformat())
                        )
                        hasFc = True

                    dest_path = os.path.join(self.logfileDir, binBaseName)
                    logging.info(f"Copying {binBaseName} to {dest_path}")
                    shutil.copyfile(binFile, dest_path)

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

            # Reset necessary attributes before parsing
            self.logdata = []
            self.zipFilename = zip_basename
            self.pathCoords = []
            self.flightStarts = {}
            self.flightEnds = {}
            self.flightStats = []
            self.flightOptions = []

            # Parse the data
            if ('p1a' in lcDM):
                logging.info("Creating P1A parser")
                parser = DreamerBaseLogParser(self)
            else:
                logging.info("Creating Atom parser")
                parser = AtomBaseLogParser(self)

            logging.info(f"Starting parse of {zip_basename}")
            parser.parse(zip_basename)
            logging.info(f"Parse completed. Found {len(self.logdata)} records")
            logging.info(f"Path coordinates: {len(self.pathCoords)} sets")

            if self.logdata:
                # Export individual KML files for each flight
                self.export_individual_flights(zip_basename, drone_model, parser)
            else:
                logging.warning(f"No flight data found in {zip_basename}")

        else:
            logging.warning("Nothing to import - no FC files found")

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def process_zip_file(self, zip_path: str):
        """Main entry point for processing a new ZIP file"""
        try:
            self.initiate_import_file(zip_path)
        except Exception as e:
            logging.error(f"Error processing {zip_path}: {e}", exc_info=True)

    # Properties needed by the parser
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
    def __init__(self, processor: FlightLogProcessor):
        self.processor = processor

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.lower().endswith('.zip'):
            logging.info(f"New file detected: {event.src_path}")
            # Wait a moment to ensure file is completely written
            time.sleep(1)
            self.processor.process_zip_file(event.src_path)


def main():
    input_dir = "/home/jake/uploads"
    output_dir = "/home/jake/kml-viewer/public"

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
