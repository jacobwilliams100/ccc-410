# Dronenex.py - Based on main.py by Koen Aerts and Rob Pritt from PotDroneFlightParser
# Part of Jacob Williams' Dronenex.us project
# Re-implements functionality from main.py, but designed to run headless and automatically process Zipped Potensic logs into KML files as they are moved into a directory

#!/usr/bin/env python3
import os
import time
import re
import logging
import shutil
import json
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
        # Update output directory to use kml subfolder
        self.output_dir = os.path.join(output_dir, "kml")
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

    def extract_video_metadata(self, video_path):
        """Extract metadata from video files including duration, resolution and framerate"""
        try:
            # Try to use moviepy if available - with more robust error handling
            duration = 0
            resolution = "unknown"
            framerate = 0
            try:
                # Import moviepy modules directly to see exact error if it fails
                import sys
                logging.info(f"Python path: {sys.path}")

                import moviepy
                logging.info(f"Found moviepy version: {moviepy.__version__}")

                # Try direct access to core components instead of using the editor module
                try:
                    from moviepy.video.io.VideoFileClip import VideoFileClip
                    video = VideoFileClip(video_path)
                    duration = video.duration
                    resolution = f"{video.size[0]}x{video.size[1]}"
                    framerate = video.fps  # Get the framerate (frames per second)
                    video.close()
                    logging.info(
                        f"Successfully extracted video info using moviepy: duration={duration}s, resolution={resolution}, fps={framerate}")
                except Exception as editor_error:
                    logging.warning(f"Error with moviepy VideoFileClip: {editor_error}")
                    # Try fallback method using subprocess
                    raise

            except ImportError as e:
                logging.warning(f"moviepy not installed or import error: {e}")
            except Exception as e:
                logging.warning(f"Error using moviepy: {e}")
                # Try fallback method for duration if available
                try:
                    import subprocess
                    # Try using ffprobe to get duration
                    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                           "-of", "default=noprint_wrappers=1:nokey=1", video_path]
                    duration = float(subprocess.check_output(cmd).decode('utf-8').strip())
                    logging.info(f"Got duration using ffprobe: {duration}s")

                    # Try to get framerate using ffprobe too
                    fps_cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
                               "-show_entries", "stream=r_frame_rate",
                               "-of", "default=noprint_wrappers=1:nokey=1", video_path]
                    fps_output = subprocess.check_output(fps_cmd).decode('utf-8').strip()
                    # Frame rate often comes as a fraction like "30000/1001"
                    if '/' in fps_output:
                        num, denom = map(int, fps_output.split('/'))
                        framerate = num / denom
                    else:
                        framerate = float(fps_output)
                    logging.info(f"Got framerate using ffprobe: {framerate}fps")

                    # Try to get resolution using ffprobe too
                    res_cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
                               "-show_entries", "stream=width,height",
                               "-of", "default=noprint_wrappers=1:nokey=1", video_path]
                    res_output = subprocess.check_output(res_cmd).decode('utf-8').strip()
                    res_parts = res_output.split('\n')
                    if len(res_parts) >= 2:
                        width = int(res_parts[0])
                        height = int(res_parts[1])
                        resolution = f"{width}x{height}"
                        logging.info(f"Got resolution using ffprobe: {resolution}")
                except Exception as ffprobe_error:
                    logging.warning(f"Fallback metadata detection failed: {ffprobe_error}")

            # Get file modification time as fallback
            file_time = os.path.getmtime(video_path)
            creation_time = datetime.datetime.fromtimestamp(file_time)

            # Try to extract more accurate timestamp from filename
            filename = os.path.basename(video_path)

            # Format specific to your drone videos: 100DRONE_NORM000X_YYYYMMDDHHMMSS.mp4
            drone_match = re.search(r'_(\d{8})(\d{6})\.', filename)
            if drone_match:
                date_part = drone_match.group(1)  # YYYYMMDD
                time_part = drone_match.group(2)  # HHMMSS

                year = int(date_part[0:4])
                month = int(date_part[4:6])
                day = int(date_part[6:8])

                hour = int(time_part[0:2])
                minute = int(time_part[2:4])
                second = int(time_part[4:6])

                try:
                    creation_time = datetime.datetime(year, month, day, hour, minute, second)
                    logging.info(f"Extracted timestamp from filename: {creation_time}")
                except ValueError as e:
                    logging.warning(f"Invalid date in filename: {e}")
            else:
                # Try more generic patterns as fallback
                generic_match = re.search(r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})[-_]?(\d{2})[-_]?(\d{2})[-_]?(\d{2})',
                                          filename)
                if generic_match:
                    # Extract timestamp from filename
                    year, month, day, hour, minute, second = map(int, generic_match.groups())
                    try:
                        creation_time = datetime.datetime(year, month, day, hour, minute, second)
                        logging.info(f"Extracted timestamp from filename: {creation_time}")
                    except ValueError as e:
                        logging.warning(f"Invalid date in filename: {e}")

            return {
                'timestamp': creation_time.isoformat(),
                'duration': duration,
                'resolution': resolution,
                'framerate': framerate
            }
        except Exception as e:
            logging.error(f"Error extracting video metadata from {video_path}: {e}")
            # Fallback on error
            file_time = os.path.getmtime(video_path)
            creation_time = datetime.datetime.fromtimestamp(file_time)
            return {
                'timestamp': creation_time.isoformat(),
                'duration': 0,
                'resolution': "unknown",
                'framerate': 0
            }

    def process_video_file(self, video_path):
        """Process a standalone video file (not in a ZIP)"""
        if not os.path.isfile(video_path):
            logging.error(f"Error: File does not exist - {video_path}")
            return

        videoBaseName = os.path.basename(video_path)
        logging.info(f"Processing standalone video: {videoBaseName}")

        # Create videos directory if it doesn't exist
        videos_dir = os.path.join(os.path.dirname(self.output_dir), "videos")
        Path(videos_dir).mkdir(parents=True, exist_ok=True)

        video_dest_path = os.path.join(videos_dir, videoBaseName)

        try:
            # Copy the video file
            shutil.copyfile(video_path, video_dest_path)
            logging.info(f"Video copied to: {video_dest_path}")

            # Extract metadata
            metadata = self.extract_video_metadata(video_path)
            logging.info(
                f"Video metadata: timestamp={metadata['timestamp']}, duration={metadata['duration']}s, fps={metadata['framerate']}")

            # Update the metadata JSON file
            metadata_file = os.path.join(videos_dir, 'video_metadata.json')

            # Read existing metadata if file exists
            video_metadata = []
            if os.path.exists(metadata_file):
                try:
                    with open(metadata_file, 'r') as f:
                        video_metadata = json.load(f)
                except json.JSONDecodeError:
                    logging.warning(f"Error reading video metadata file, creating new one")

            # Create the video entry
            video_entry = {
                'filename': videoBaseName,
                'timestamp': metadata['timestamp'],
                'duration': metadata['duration'],
                'resolution': metadata['resolution'],
                'framerate': metadata['framerate']
            }

            # Replace existing entry or add new one
            found = False
            for i, entry in enumerate(video_metadata):
                if entry.get('filename') == videoBaseName:
                    video_metadata[i] = video_entry
                    found = True
                    break

            if not found:
                video_metadata.append(video_entry)

            # Write updated metadata
            with open(metadata_file, 'w') as f:
                json.dump(video_metadata, f, indent=2)

            logging.info(f"Updated video metadata JSON file for web server")

            # Delete the original file to save space
            try:
                os.remove(video_path)
                logging.info(f"Deleted original video file: {video_path}")
            except Exception as del_error:
                logging.error(f"Error deleting original video file: {del_error}", exc_info=True)

        except Exception as e:
            logging.error(f"Error processing video file: {e}", exc_info=True)

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

            # FIXED: Create a dictionary for flight stats instead of a list
            flight_stats = {}
            flight_stats[0] = self.flightStats[0]  # Overall stats
            flight_num_int = int(flight_num)
            flight_stats[1] = self.flightStats[flight_num_int]  # Current flight stats

            # Log the max speed for debugging
            logging.debug(f"Flight {flight_num} max speed from flightStats: {self.flightStats[flight_num_int][2]}")

            # Extract flight-specific path coordinates
            flight_path_coords = None
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
        videoList = []  # New list for video files

        # Extract the bin files and copy to the app data directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)

        with ZipFile(selected_file, 'r') as unzip:
            logging.info(f"ZIP contents: {unzip.namelist()}")
            unzip.extractall(path=self.temp_dir)

        # First check for video files (MP4/MOV)
        for videoFile in glob.glob(os.path.join(self.temp_dir, '**/*.mp4'), recursive=True) + \
                         glob.glob(os.path.join(self.temp_dir, '**/*.mov'), recursive=True):
            videoBaseName = os.path.basename(videoFile)
            logging.info(f"Found video file: {videoBaseName}")
            videoList.append(videoFile)

        # Process bin files as before
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

            # Process any video files found
            if videoList:
                # Create videos directory if it doesn't exist
                videos_dir = os.path.join(os.path.dirname(self.output_dir), "videos")
                Path(videos_dir).mkdir(parents=True, exist_ok=True)

                # Path for the metadata JSON file
                metadata_file = os.path.join(videos_dir, 'video_metadata.json')

                # Read existing metadata if file exists
                video_metadata = []
                if os.path.exists(metadata_file):
                    try:
                        with open(metadata_file, 'r') as f:
                            video_metadata = json.load(f)
                    except json.JSONDecodeError:
                        logging.warning(f"Error reading video metadata file, creating new one")

                for videoFile in videoList:
                    videoBaseName = os.path.basename(videoFile)
                    video_dest_path = os.path.join(videos_dir, videoBaseName)
                    logging.info(f"Copying video {videoBaseName} to {video_dest_path}")

                    # Copy the video file
                    shutil.copyfile(videoFile, video_dest_path)

                    # Extract metadata from the video
                    metadata = self.extract_video_metadata(videoFile)
                    logging.info(
                        f"Video metadata: timestamp={metadata['timestamp']}, duration={metadata['duration']}s, fps={metadata['framerate']}")

                    # Add or update this video's metadata in the array
                    video_entry = {
                        'filename': videoBaseName,
                        'timestamp': metadata['timestamp'],
                        'duration': metadata['duration'],
                        'resolution': metadata['resolution'],
                        'framerate': metadata['framerate']
                    }

                    # Replace existing entry or add new one
                    found = False
                    for i, entry in enumerate(video_metadata):
                        if entry.get('filename') == videoBaseName:
                            video_metadata[i] = video_entry
                            found = True
                            break

                    if not found:
                        video_metadata.append(video_entry)

                # Write updated metadata to JSON file
                try:
                    with open(metadata_file, 'w') as f:
                        json.dump(video_metadata, f, indent=2)
                    logging.info(f"Updated video metadata JSON file with {len(video_metadata)} entries")
                except Exception as e:
                    logging.error(f"Error writing video metadata JSON: {e}")

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

        # Remove the original ZIP file to save space
        try:
            os.remove(selected_file)
            logging.info(f"Deleted original ZIP file: {selected_file}")
        except Exception as del_error:
            logging.error(f"Error deleting original ZIP file: {del_error}", exc_info=True)

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

        file_path = event.src_path.lower()

        if file_path.endswith('.zip'):
            logging.info(f"New ZIP file detected: {event.src_path}")
            # Wait a moment to ensure file is completely written
            time.sleep(1)
            self.processor.process_zip_file(event.src_path)
        elif file_path.endswith(('.mp4', '.mov')):
            logging.info(f"New video file detected: {event.src_path}")
            # Wait a moment to ensure file is completely written
            time.sleep(1)
            self.processor.process_video_file(event.src_path)


def main():
    input_dir = "/home/jake/uploads"
    output_dir = "/home/jake/kml-viewer/public"  # Now will use subdirectories /kml and /videos

    processor = FlightLogProcessor(input_dir, output_dir)
    event_handler = LogFileHandler(processor)
    observer = Observer()
    observer.schedule(event_handler, input_dir, recursive=False)
    observer.start()

    logging.info(f"Started monitoring {input_dir} for new flight log files")
    logging.info(f"KML files will be exported to {processor.output_dir}")

    try:
        # Process any existing zip files first
        existing_files = list(Path(input_dir).glob('*.zip'))
        if existing_files:
            logging.info(f"Found {len(existing_files)} existing ZIP files to process")
            for zip_file in existing_files:
                processor.process_zip_file(str(zip_file))

        # Check for existing video files too
        existing_videos = list(Path(input_dir).glob('*.mp4')) + list(Path(input_dir).glob('*.mov'))
        if existing_videos:
            logging.info(f"Found {len(existing_videos)} existing video files to process")
            for video_file in existing_videos:
                processor.process_video_file(str(video_file))

        # Then keep running to watch for new files
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logging.info("\nStopping file monitor...")

    observer.join()


if __name__ == "__main__":
    main()
