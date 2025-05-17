# 🧠 Adalog - Neurophenomenological Data Recorder

Adalog is a Python app for recording neurophenomenological data using `goofi-pipe`. It provides an intuitive graphical interface for capturing text, drawings, and EEG signals during experimental sessions. This README covers the installation, setup, and usage of the Adalog app.

---

## 📦 Installation

### 1. Clone the repository
```bash
git clone https://github.com/KairosCreation/adalog.git
cd adalog
```

### 2. Create a Python environment
Create a new virtual environment using conda:
```bash
conda create -n adalog python=3.11
conda activate adalog
```

### 3. Install requirements
Install the necessary packages:
```bash
pip install -r requirements.txt
```

---

## 🚀 Running Adalog

### 1. Start the LSL stream
For Muse headsets:
```bash
muselsl stream
```

For other LSL-compatible devices, make sure the stream is running.

### 2. Start the Goofi-Pipe patch
Run the Goofi-Pipe patch in headless mode:
```bash
goofi-pipe adalog.gfi --headless 
```

### 3. Start the Adalog app
Run the main Adalog application:
```bash
python adalog.py
```

---

## 📝 Usage

1. **Enter Subject ID and Session Type**  
   Use the text fields to set the subject ID and session type. This will define the folder structure for your session logs.

3. **Choose Mode**  
   - **Text Mode:** Capture words and phrases.
   - **Drawing Mode:** Capture freehand sketches.

4. **Manage EEG Quality and LSL Streams**  
   - The EEG quality indicator shows the current signal quality.
   - Use the dropdown menu to select an available LSL stream.
   - Click the "🔄 Refresh Streams" button to update the list of available streams.

5. **Start/Stop Recording**  
   Use the "🟢 Start Recording" and "🔴 Stop Recording" buttons to control the recording process.

---

## 📂 Directory Structure

Sessions are saved as follows:
```
sessions/
└── SUBJECT_ID/
    └── SESSION_TYPE/
        └── TIMESTAMP/
            ├── pheno.csv
            └── drawings/
```
TODO: save the neuro.csv in the corresponding SUBJECT_ID

- **pheno.csv:** Logs words and phrases with timestamps.
- **drawings/:** Contains saved drawings as PNG files.
- **neuro.csv:** Logs EEG data with timestamps.

---

## 🛠️ Contributing

Feel free to open issues or pull requests to improve the app. Contributions are welcome!

---

## 📄 License

TODO

---

## ❤️ Acknowledgments

Thanks to the Goofi-Pipe team for providing the underlying data processing framework.
