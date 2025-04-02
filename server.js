// importing modules
const express = require('express');
const fs = require('fs');
const path = require('path');

// creating express application
const app = express();
const KML_DIRECTORY = path.join(__dirname, 'public/kml');
const VIDEOS_DIRECTORY = path.join(__dirname, 'public/videos');
const VIDEO_METADATA_FILE = path.join(VIDEOS_DIRECTORY, 'video_metadata.json');

// Create directories if they don't exist
function ensureDirectoryExists(directory) {
    if (!fs.existsSync(directory)) {
        console.log(`Creating directory: ${directory}`);
        fs.mkdirSync(directory, { recursive: true });
    }
}

// Ensure directories exist on startup
ensureDirectoryExists(KML_DIRECTORY);
ensureDirectoryExists(VIDEOS_DIRECTORY);

// We will serve files from the directory: public
app.use(express.static('public'));

// Load video metadata from JSON file
function loadVideoMetadata() {
    try {
        if (fs.existsSync(VIDEO_METADATA_FILE)) {
            const data = fs.readFileSync(VIDEO_METADATA_FILE, 'utf8');
            return JSON.parse(data);
        }
        return [];
    } catch (err) {
        console.error('Error loading video metadata:', err);
        return [];
    }
}

// Enhanced list_kml endpoint that includes video availability info
app.get('/list_kml', (req, res) => {
    // read directory to get list of files
    fs.readdir(KML_DIRECTORY, (err, files) => {
        if (err) {
            console.error('Error reading KML directory:', err);
            return res.status(500).json({ error: 'Failed to read directory' });
        }
        
        // filter out non-KML files
        const kmlFiles = files.filter(file => file.endsWith('.kml'));
        
        // Load video metadata
        const videoMetadata = loadVideoMetadata();
        
        // Create enhanced file info with video availability
        const kmlInfo = kmlFiles.map(file => {
            // Extract timestamp from filename (format: YYYYMMDD_HHMMSS.kml)
            const match = file.match(/(\d{8})_(\d{6})\.kml/);
            let timestamp = null;
            let hasVideo = false;
            let bestVideoMatch = null;
            
            if (match) {
                // Parse the timestamp from the filename
                const dateStr = match[1];
                const timeStr = match[2];
                
                // Recreate ISO timestamp
                const year = dateStr.substring(0, 4);
                const month = dateStr.substring(4, 6);
                const day = dateStr.substring(6, 8);
                
                const hour = timeStr.substring(0, 2);
                const minute = timeStr.substring(2, 4);
                const second = timeStr.substring(4, 6);
                
                timestamp = `${year}-${month}-${day}T${hour}:${minute}:${second}`;
                
                // Check if there's a matching video for this timestamp
                if (videoMetadata.length > 0) {
                    // Find the closest video by timestamp
                    const flightDate = new Date(timestamp);
                    
                    // Score videos by timestamp proximity
                    const scoredVideos = videoMetadata.map(video => {
                        const videoDate = new Date(video.timestamp);
                        const diffMs = Math.abs(videoDate - flightDate);
                        const diffMinutes = diffMs / (1000 * 60);
                        
                        // Return videos within 15 minutes with a score
                        return { 
                            video,
                            diffMinutes,
                            score: diffMinutes <= 15 ? (15 - diffMinutes) : -1 
                        };
                    });
                    
                    // Filter and sort by score
                    const matches = scoredVideos
                        .filter(item => item.score >= 0)
                        .sort((a, b) => b.score - a.score);
                    
                    // If we have a match within 15 minutes
                    if (matches.length > 0) {
                        hasVideo = true;
                        bestVideoMatch = {
                            filename: matches[0].video.filename,
                            timeOffset: Math.round(matches[0].diffMinutes),
                            duration: matches[0].video.duration
                        };
                    }
                }
            }
            
            return {
                path: `kml/${file}`,
                filename: file,
                timestamp: timestamp,
                hasVideo: hasVideo,
                videoInfo: bestVideoMatch
            };
        });
        
        // Sort by timestamp (newest first)
        kmlInfo.sort((a, b) => {
            if (!a.timestamp && !b.timestamp) return 0;
            if (!a.timestamp) return 1;
            if (!b.timestamp) return -1;
            return new Date(b.timestamp) - new Date(a.timestamp);
        });
        
        res.json(kmlInfo);
    });
});

// API endpoint to check if a video exists for a given timestamp
app.get('/video_for_flight', (req, res) => {
    const flightTimestamp = req.query.timestamp;
    const flightDuration = parseFloat(req.query.duration || '0');
    
    if (!flightTimestamp) {
        return res.status(400).json({ error: 'No timestamp provided' });
    }
    
    try {
        // Parse the flight timestamp string to a Date object
        const flightDate = new Date(flightTimestamp);
        
        // Load video metadata
        const videoMetadata = loadVideoMetadata();
        
        if (videoMetadata.length === 0) {
            return res.json({
                hasVideo: false,
                message: "No videos available"
            });
        }
        
        console.log(`Searching for video matching flight at ${flightDate.toISOString()} with duration ${flightDuration}s`);
        
        // Calculate matching scores for each video
        const scoredVideos = videoMetadata.map(video => {
            const videoDate = new Date(video.timestamp);
            
            // Calculate time difference in minutes
            const diffMs = Math.abs(videoDate - flightDate);
            const diffMinutes = diffMs / (1000 * 60);
            
            // Don't consider videos more than 15 minutes apart
            if (diffMinutes > 15) {
                return { video, score: -1 }; // Negative score means no match
            }
            
            // Start with a base score (10 means perfect match)
            let score = 10;
            
            // Subtract points for timestamp difference (up to 5 points)
            // 0 minutes apart = -0 points, 5 minutes apart = -3 points, 15 minutes apart = -5 points
            score -= Math.min(5, diffMinutes / 3);
            
            // If both flight and video have duration info, factor that in
            if (flightDuration > 0 && video.duration > 0) {
                const durationRatio = flightDuration / video.duration;
                
                // Calculate how well the durations match
                if (durationRatio > 2 || durationRatio < 0.2) {
                    // Very different durations - likely not a match
                    score -= 5;
                } else if (durationRatio > 1.5 || durationRatio < 0.5) {
                    // Somewhat different durations
                    score -= 3;
                } else if (durationRatio > 1.2 || durationRatio < 0.8) {
                    // Slightly different durations
                    score -= 1;
                }
                
                // Typical case: video starts before flight and ends after
                // This gives a bonus if the video is longer than the flight but not too much longer
                if (durationRatio >= 0.7 && durationRatio <= 0.95) {
                    score += 1; // Small bonus for ideal case
                }
                
                console.log(`Video ${video.filename}: timestamp diff=${diffMinutes.toFixed(1)}min, duration=${video.duration}s vs flight=${flightDuration}s, ratio=${durationRatio.toFixed(2)}, score=${score.toFixed(1)}`);
            } else {
                console.log(`Video ${video.filename}: timestamp diff=${diffMinutes.toFixed(1)}min, no duration comparison, score=${score.toFixed(1)}`);
            }
            
            return { video, score };
        });
        
        // Filter out negative scores and sort by score (highest first)
        const matches = scoredVideos
            .filter(item => item.score >= 0)
            .sort((a, b) => b.score - a.score);
        
        if (matches.length > 0) {
            const bestMatch = matches[0].video;
            console.log(`Best match: ${bestMatch.filename} with score ${matches[0].score.toFixed(1)}`);
            
            return res.json({
                hasVideo: true,
                videoPath: `videos/${bestMatch.filename}`,
                videoName: bestMatch.filename,
                videoDuration: bestMatch.duration,
                videoTimestamp: bestMatch.timestamp,
                resolution: bestMatch.resolution,
                framerate: bestMatch.framerate || 30, // Default to 30 if not available
                score: matches[0].score
            });
        } else {
            console.log('No matching videos found');
            return res.json({
                hasVideo: false,
                message: "No matching videos found for this flight"
            });
        }
    } catch (error) {
        console.error('Error matching video for flight:', error);
        return res.status(500).json({ 
            hasVideo: false, 
            error: 'Error processing video matching',
            message: error.message
        });
    }
});

// API endpoint to list all available videos
app.get('/list_videos', (req, res) => {
    try {
        const videoMetadata = loadVideoMetadata();
        
        // Format the response with additional information
        const videos = videoMetadata.map(video => {
            // Convert timestamp to readable format
            const timestamp = new Date(video.timestamp);
            const formattedDate = timestamp.toLocaleDateString();
            const formattedTime = timestamp.toLocaleTimeString();
            
            // Format duration
            const minutes = Math.floor(video.duration / 60);
            const seconds = Math.floor(video.duration % 60);
            const formattedDuration = `${minutes}:${seconds.toString().padStart(2, '0')}`;
            
            return {
                filename: video.filename,
                path: `videos/${video.filename}`,
                timestamp: video.timestamp,
                formattedDate: formattedDate,
                formattedTime: formattedTime,
                duration: video.duration,
                formattedDuration: formattedDuration,
                resolution: video.resolution,
                framerate: video.framerate || 30 // Default to 30 if not available
            };
        });
        
        // Sort by timestamp (newest first)
        videos.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        
        res.json(videos);
    } catch (error) {
        console.error('Error listing videos:', error);
        res.status(500).json({ error: 'Failed to list videos' });
    }
});

//start server
const PORT = 3000;
app.listen(PORT, () => {
    console.log(`Server running at http://localhost:${PORT}`);
    console.log(`KML files directory: ${KML_DIRECTORY}`);
    console.log(`Videos directory: ${VIDEOS_DIRECTORY}`);
});
