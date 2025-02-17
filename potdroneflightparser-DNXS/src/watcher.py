# watchdog necessary to watch directory.
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time
import os
import re

# hardcoded directory to watch.
WATCH_DIRECTORY = "/home/jake/uploads/"

# handler for watching directory and reacting to events.
class ZipFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.zip'):
            print(f"New ZIP file detected: {event.src_path}")
            initiate_import_file(event.src_path)

# placeholder function to process the zip file.
def initiate_import_file(selectedFile):
    ''' Simulate processing a ZIP file. Replace with real processing logic. '''
    if os.path.isfile(selectedFile):
        print(f"Processing file: {selectedFile}")

        zipBaseName = os.path.basename(selectedFile)
        droneModel = re.sub(r"[0-9]*-(.*)-Drone.*", r"\1", zipBaseName)  # Pull drone model from zip filename.
        droneModel = re.sub(r"[^\w]", r" ", droneModel)  # Remove non-alphanumeric characters from the model name.
        lcDM = droneModel.lower()


    else:
        print(f"Error: File does not exist - {selectedFile}")

# function starts the watcher, monitoring directory for changes.
def start_watching(directory):
    ''' Watch a directory for new ZIP files and process them. '''
    event_handler = ZipFileHandler()
    observer = Observer()
    observer.schedule(event_handler, directory, recursive=False)
    observer.start()

    try:
        # print watched directory.
        print(f"Watching directory: {directory}")
        # checks every second (for now).
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # manual stop from user.
        observer.stop()
        print("Stopped watching.")
    observer.join()

# Create directory if it doesn't exist.
if __name__ == "__main__":
    if not os.path.exists(WATCH_DIRECTORY):
        print(f"Error: Directory '{WATCH_DIRECTORY}' does not exist. Creating it...")
        os.makedirs(WATCH_DIRECTORY)

    start_watching(WATCH_DIRECTORY)
