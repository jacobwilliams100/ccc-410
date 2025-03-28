import datetime
import xml.etree.ElementTree as ET
import logging


class ExportCsv:
    def __init__(self, columnnames=[], rows=[]):
        self.columns = columnnames
        self.rows = rows

    def save(self, csvFilename):
        with open(csvFilename, 'w') as f:
            head = ''
            for col in self.columns:
                if len(head) > 0:
                    head = head + ','
                head = head + col
            f.write(head)
            for record in self.rows:
                hasWritten = False
                f.write('\n')
                for col in record:
                    if (hasWritten):
                        f.write(',')
                    f.write('"' + str(col) + '"')
                    hasWritten = True
        f.close()


class ExportKml:
    appRef = '<a href="https://github.com/koen-aerts/potdroneflightparser">Flight Log Viewer</a>'
    appAssetSrc = "https://raw.githubusercontent.com/koen-aerts/potdroneflightparser/v2.2.0/src/assets"

    def __init__(
            self, commonlib, columnnames=[], rows=[], name="Flight Logs", description=appRef, pathcolor="#ff0000",
            pathwidth="1", homecolorref="1", ctrlcolorref="1", dronecolorref="1", flightstarts=[],
            flightends=[], flightstats=[], pathCoords=None, uom="metric"
    ):
        self.common = commonlib
        self.columns = columnnames
        self.rows = rows
        self.logName = name
        self.logDescription = description
        self.homeColor = homecolorref
        self.ctrlColor = ctrlcolorref
        self.droneColor = dronecolorref
        self.pathColor = pathcolor
        self.pathWidth = pathwidth
        self.flightStarts = flightstarts
        self.flightEnds = flightends
        self.flightStats = flightstats
        self.pathCoords = pathCoords
        self.uom = uom

    def save(self, kmlFilename):
        try:
            root = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
            doc = ET.SubElement(root, "Document")
            ET.SubElement(doc, "name").text = self.logName
            ET.SubElement(doc, "description").text = self.logDescription

            # Add styles
            self._add_styles(doc)

            # For single flight export, we only process one flight
            for flightNo in self.flightStarts.keys():
                coords = ''
                self.currentStartIdx = self.flightStarts[flightNo]
                self.currentEndIdx = self.flightEnds[flightNo]

                # Create flight folder
                folder = self._create_flight_folder(doc, flightNo)

                prevtimestamp = None
                maxelapsedms = datetime.timedelta(microseconds=500000)
                isfirstrow = True

                # Process flight data
                for rowIdx in range(self.currentStartIdx, self.currentEndIdx + 1):
                    if rowIdx < len(self.rows):
                        row = self.rows[rowIdx]
                        coords = self._process_flight_row(folder, row, coords, prevtimestamp, maxelapsedms, isfirstrow)
                        if isfirstrow:
                            isfirstrow = False

                        # Update prevtimestamp for next iteration
                        try:
                            timestamp_idx = self.columns.index('timestamp')
                            if timestamp_idx < len(row):
                                thistimestamp = datetime.datetime.fromisoformat(row[timestamp_idx])
                                prevtimestamp = thistimestamp
                        except (ValueError, IndexError) as e:
                            logging.error(f"Error processing timestamp: {e}")
                            prevtimestamp = None

                # Add flight path
                if self.pathCoords:
                    self._add_flight_path_from_coords(folder, self.pathCoords, flightNo)
                else:
                    self._add_flight_path(folder, coords, flightNo)

            # Write the KML file
            xml = ET.ElementTree(root)
            xml.write(kmlFilename, encoding='UTF-8', xml_declaration=True)
            logging.info(f"Successfully saved KML file: {kmlFilename}")

        except Exception as e:
            logging.error(f"Error saving KML file: {e}", exc_info=True)
            raise

    def _add_styles(self, doc):
        # Path style
        style = ET.SubElement(doc, "Style", id="pathStyle")
        lineStyle = ET.SubElement(style, "LineStyle")
        ET.SubElement(lineStyle, "color").text = f"ff{self.pathColor[5:7]}{self.pathColor[3:5]}{self.pathColor[1:3]}"
        ET.SubElement(lineStyle, "width").text = self.pathWidth

        # Home marker style
        style = ET.SubElement(doc, "Style", id="homeStyle")
        iconStyle = ET.SubElement(style, "IconStyle")
        icon = ET.SubElement(iconStyle, "Icon")
        ET.SubElement(icon, "href").text = f"{self.appAssetSrc}/Home-{self.homeColor}.png"
        ET.SubElement(iconStyle, "hotSpot", x="0.5", y="0.5", xunits="fraction", yunits="fraction")

        # Controller marker style
        style = ET.SubElement(doc, "Style", id="ctrlStyle")
        iconStyle = ET.SubElement(style, "IconStyle")
        icon = ET.SubElement(iconStyle, "Icon")
        ET.SubElement(icon, "href").text = f"{self.appAssetSrc}/Controller-{self.ctrlColor}.png"
        ET.SubElement(iconStyle, "hotSpot", x="0.5", y="0.5", xunits="fraction", yunits="fraction")

        # Drone marker style
        style = ET.SubElement(doc, "Style", id="droneStyle")
        iconStyle = ET.SubElement(style, "IconStyle")
        icon = ET.SubElement(iconStyle, "Icon")
        ET.SubElement(icon, "href").text = f"{self.appAssetSrc}/Drone-{self.droneColor}.png"
        ET.SubElement(iconStyle, "hotSpot", x="0.5", y="0.5", xunits="fraction", yunits="fraction")

        # Points style
        style = ET.SubElement(doc, "Style", id="hidePoints")
        listStyle = ET.SubElement(style, "ListStyle")
        ET.SubElement(listStyle, "listItemType").text = "checkHideChildren"

    def _create_flight_folder(self, doc, flightNo):
        folder = ET.SubElement(doc, "Folder")
        ET.SubElement(folder, "name").text = f"Flight #{flightNo}"

        try:
            flight_idx = int(flightNo)

            # Check if this flight has stats in the flightStats array
            if flight_idx < len(self.flightStats):
                # Extract values from flightStats
                duration = str(self.flightStats[flight_idx][3]) if self.flightStats[flight_idx][3] is not None else "0"
                distance = self.common.fmt_num(self.common.dist_val(
                    self.flightStats[flight_idx][9] if self.flightStats[flight_idx][9] is not None else 0
                ))
                max_altitude = self.common.fmt_num(self.common.dist_val(
                    self.flightStats[flight_idx][1] if self.flightStats[flight_idx][1] is not None else 0
                ))
                max_speed = self.common.fmt_num(self.common.speed_val(
                    self.flightStats[flight_idx][2] if self.flightStats[flight_idx][2] is not None else 0
                ))

                # Create the description text
                description_text = f"Duration: {duration}<br>Distance flown: {distance} {self.common.dist_unit()}<br>Max altitude: {max_altitude} {self.common.dist_unit()}<br>Max speed: {max_speed} {self.common.speed_unit()}"

                logging.info(
                    f"Using stats from flightStats for flight {flightNo}: alt={max_altitude}, speed={max_speed}")
            else:
                # For flights without flightStats entries, calculate directly from flight data
                max_altitude = 0
                max_speed = 0

                # Calculate max values from flight data rows
                for row_idx in range(self.currentStartIdx, self.currentEndIdx + 1):
                    if row_idx < len(self.rows):
                        row = self.rows[row_idx]
                        # Check for altitude
                        try:
                            alt_idx = self.columns.index('altitude2metric')
                            if alt_idx < len(row) and row[alt_idx]:
                                try:
                                    altitude = float(row[alt_idx])
                                    max_altitude = max(max_altitude, altitude)
                                except (ValueError, TypeError):
                                    pass
                        except ValueError:
                            # Try alternative altitude column if needed
                            pass

                        # Try to find speed using the correct column name - try multiple possibilities
                        try:
                            speed_idx = self.columns.index('speed2')
                            if speed_idx < len(row) and row[speed_idx]:
                                try:
                                    speed = float(row[speed_idx])
                                    max_speed = max(max_speed, speed)
                                except (ValueError, TypeError):
                                    pass
                        except ValueError:
                            # Try several alternative column names
                            for col_name in ['speed2metric', 'speed1', 'speed', 'speed2latmetric', 'speed2lonmetric']:
                                try:
                                    speed_idx = self.columns.index(col_name)
                                    if speed_idx < len(row) and row[speed_idx]:
                                        try:
                                            speed = float(row[speed_idx])
                                            max_speed = max(max_speed, speed)
                                            break  # Found valid speed, exit the loop
                                        except (ValueError, TypeError):
                                            pass
                                except ValueError:
                                    continue  # Column not found, try the next one

                # Format max values
                max_altitude_fmt = self.common.fmt_num(self.common.dist_val(max_altitude))
                max_speed_fmt = self.common.fmt_num(self.common.speed_val(max_speed))

                # Calculate duration
                duration = "Unknown"
                if self.currentStartIdx < len(self.rows) and self.currentEndIdx < len(self.rows):
                    try:
                        timestamp_idx = self.columns.index('timestamp')
                        first_ts = datetime.datetime.fromisoformat(self.rows[self.currentStartIdx][timestamp_idx])
                        last_ts = datetime.datetime.fromisoformat(self.rows[self.currentEndIdx][timestamp_idx])
                        duration = str(last_ts - first_ts)
                    except (ValueError, IndexError):
                        pass

                # Calculate distance (estimated)
                distance = "Unknown"

                # Create description text with calculated values
                description_text = f"Duration: {duration}<br>Distance flown: {distance} {self.common.dist_unit()}<br>Max altitude: {max_altitude_fmt} {self.common.dist_unit()}<br>Max speed: {max_speed_fmt} {self.common.speed_unit()}"

                logging.info(f"Computed stats for flight {flightNo}: alt={max_altitude_fmt}, speed={max_speed_fmt}")

            # Set the description as plain text (avoiding CDATA issues)
            ET.SubElement(folder, "description").text = description_text

        except Exception as e:
            logging.warning(f"Error creating flight folder description: {e}")
            ET.SubElement(folder, "description").text = f"Flight #{flightNo}"

        ET.SubElement(folder, "styleUrl").text = "#hidePoints"
        ET.SubElement(folder, "visibility").text = "0"
        return folder

    def _process_flight_row(self, folder, row, coords, prevtimestamp, maxelapsedms, isfirstrow):
        try:
            # Find timestamp index
            timestamp_idx = self.columns.index('timestamp')
            if timestamp_idx >= len(row):
                logging.warning(f"Row does not have enough elements for timestamp")
                return coords

            thistimestamp = datetime.datetime.fromisoformat(row[timestamp_idx])
            elapsedFrame = None if prevtimestamp is None else thistimestamp - prevtimestamp

            # Format timestamp for KML - always use UTC timezone
            timestampstr = thistimestamp.astimezone(datetime.timezone.utc).isoformat()

            # Get coordinates
            try:
                dronelon_idx = self.columns.index('dronelon')
                dronelat_idx = self.columns.index('dronelat')
                dronealt_idx = self.columns.index('altitude2metric')

                if all(idx < len(row) for idx in [dronelon_idx, dronelat_idx, dronealt_idx]):
                    dronelon = row[dronelon_idx]
                    dronelat = row[dronelat_idx]
                    dronealt = row[dronealt_idx]
                else:
                    logging.warning("Row does not have all required coordinate elements")
                    return coords

                # Add lookAt element for first row
                if isfirstrow:
                    self._add_look_at(folder, dronelon, dronelat, flight_idx=int(list(self.flightStarts.keys())[0]))

                # Add drone marker with timestamp
                self._add_drone_marker(folder, timestampstr, dronelon, dronelat, dronealt)

                # Update coords string for path
                if coords:
                    coords += '\n'
                coords += f"{dronelon},{dronelat},{dronealt}"

                # Add home marker if available
                homelon_idx = self.columns.index('homelon')
                homelat_idx = self.columns.index('homelat')
                if homelon_idx < len(row) and homelat_idx < len(row):
                    homelon = row[homelon_idx]
                    homelat = row[homelat_idx]
                    if homelon != '0.0' and homelat != '0.0':
                        # Only add timestamp to the home marker if it's the first one
                        if isfirstrow:
                            self._add_home_marker(folder, timestampstr, homelon, homelat)
                        else:
                            self._add_home_marker(folder, None, homelon, homelat)

                # Add controller marker if available
                ctrllon_idx = self.columns.index('ctrllon')
                ctrllat_idx = self.columns.index('ctrllat')
                if ctrllon_idx < len(row) and ctrllat_idx < len(row):
                    ctrllon = row[ctrllon_idx]
                    ctrllat = row[ctrllat_idx]
                    if ctrllon != '0.0' and ctrllat != '0.0':
                        # Only add timestamp to the controller marker if it's the first one
                        if isfirstrow:
                            self._add_controller_marker(folder, timestampstr, ctrllon, ctrllat)
                        else:
                            self._add_controller_marker(folder, None, ctrllon, ctrllat)

            except (ValueError, IndexError) as e:
                logging.error(f"Error processing drone coordinates: {e}")

            return coords

        except (ValueError, IndexError) as e:
            logging.error(f"Error processing flight row: {e}")
            return coords

    def _add_look_at(self, folder, lon, lat, flight_idx=0):
        lookAt = ET.SubElement(folder, "LookAt")
        ET.SubElement(lookAt, "longitude").text = lon
        ET.SubElement(lookAt, "latitude").text = lat
        ET.SubElement(lookAt, "altitude").text = "200"
        ET.SubElement(lookAt, "heading").text = "0"
        ET.SubElement(lookAt, "tilt").text = "45"

        # Set a good viewing distance based on flight data if available
        if flight_idx < len(self.flightStats) and self.flightStats[flight_idx][0] is not None:
            # Use max distance to calculate view range
            range_value = str((self.flightStats[flight_idx][0] * 2) + 500)
        else:
            range_value = "500"

        ET.SubElement(lookAt, "range").text = range_value
        ET.SubElement(lookAt, "altitudeMode").text = "relativeToGround"

    def _add_drone_marker(self, folder, timestamp, lon, lat, alt):
        placeMark = ET.SubElement(folder, "Placemark")

        # Always add timestamp for drone markers
        if timestamp:
            timest = ET.SubElement(placeMark, "TimeStamp")
            ET.SubElement(timest, "when").text = timestamp

        ET.SubElement(placeMark, "styleUrl").text = "#droneStyle"
        point = ET.SubElement(placeMark, "Point")
        ET.SubElement(point, "altitudeMode").text = "relativeToGround"
        ET.SubElement(point, "coordinates").text = f"{lon},{lat},{alt}"

    def _add_home_marker(self, folder, timestamp, lon, lat):
        placeMark = ET.SubElement(folder, "Placemark")

        # Only add timestamp for the first home marker
        if timestamp:
            timest = ET.SubElement(placeMark, "TimeStamp")
            ET.SubElement(timest, "when").text = timestamp

        ET.SubElement(placeMark, "styleUrl").text = "#homeStyle"
        point = ET.SubElement(placeMark, "Point")
        ET.SubElement(point, "altitudeMode").text = "relativeToGround"
        ET.SubElement(point, "coordinates").text = f"{lon},{lat},0"

    def _add_controller_marker(self, folder, timestamp, lon, lat):
        placeMark = ET.SubElement(folder, "Placemark")

        # Only add timestamp for the first controller marker
        if timestamp:
            timest = ET.SubElement(placeMark, "TimeStamp")
            ET.SubElement(timest, "when").text = timestamp

        ET.SubElement(placeMark, "styleUrl").text = "#ctrlStyle"
        point = ET.SubElement(placeMark, "Point")
        ET.SubElement(point, "altitudeMode").text = "relativeToGround"
        ET.SubElement(point, "coordinates").text = f"{lon},{lat},1.5"

    def _add_flight_path(self, folder, coords, flightNo):
        if not coords:
            return  # Skip if no coordinates

        placeMark = ET.SubElement(folder, "Placemark")
        ET.SubElement(placeMark, "name").text = f"Flight Path {flightNo}"
        ET.SubElement(placeMark, "styleUrl").text = "#pathStyle"
        lineString = ET.SubElement(placeMark, "LineString")
        ET.SubElement(lineString, "tessellate").text = "1"
        ET.SubElement(lineString, "altitudeMode").text = "relativeToGround"
        ET.SubElement(lineString, "coordinates").text = coords

    def _add_flight_path_from_coords(self, folder, pathCoords, flightNo):
        if not pathCoords or len(pathCoords) == 0:
            return  # Skip if no coordinates

        placeMark = ET.SubElement(folder, "Placemark")
        ET.SubElement(placeMark, "name").text = f"Flight Path {flightNo}"
        ET.SubElement(placeMark, "styleUrl").text = "#pathStyle"
        lineString = ET.SubElement(placeMark, "LineString")
        ET.SubElement(lineString, "tessellate").text = "1"
        ET.SubElement(lineString, "altitudeMode").text = "relativeToGround"

        coords_text = ""
        for segment in pathCoords:
            for point in segment:
                if len(point) >= 2:
                    lon, lat = point[0], point[1]
                    alt = 0 if len(point) < 3 else point[2]
                    coords_text += f"{lon},{lat},{alt}\n"

        ET.SubElement(lineString, "coordinates").text = coords_text
