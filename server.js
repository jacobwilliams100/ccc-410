// importing modules
const express = require('express');
const fs = require('fs');
const path = require('path');

// creating express application
const app = express();
const KML_DIRECTORY = path.join(__dirname, 'public');

// We will serve files from the directory: public
app.use(express.static('public'));

// list KML files
app.get('/list_kml', (req, res)=> {

    // read directory to get list of files
	fs.readdir(KML_DIRECTORY, (err, files) => {
		if (err) {
			return res.status(500).json({ error: 'Failed to read directory' });
		}
		
		// filter out non-KML files
		const kmlFiles = files.filter(file => file.endsWith('kml'));
		res.json(kmlFiles);
	});
});

//start server
const PORT = 3000;
app.listen(PORT, () => {
	console.log(`Server running at http://localhost:${PORT}`);
});
