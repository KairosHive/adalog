<p align="center">
  <img src="https://github.com/user-attachments/assets/4dcdb86c-61b9-46f9-a337-43bb1a4265c6" alt="logo" width="300">
</p>

# Neurophenomenological Data Recorder

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

## 🚀 Running Adalog-Sense

### 1. Start the LSL stream
For Muse headsets:
```bash
muselsl stream
```

For other LSL-compatible devices, make sure the stream is running.

### 2. Start the Adalog app
Run the main Adalog application:
```bash
adalog-sense
```

---

## 📝 Usage

1. **Define Your Username**  
   Enter your username in the designated field. This will be used to identify your session and organize your logs.

2. **Choose Your Tags**  
   Enter one or more tags to describe your session (e.g., `AutomaticWriting`, `AutomaticDrawing`).  
   - Tags previously used will appear automatically as you type.
   - You can add multiple tags to categorize your session as needed.

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
    └── TIMESTAMP/
        ├── tags.csv
        └── Eeg/
            ├── eeg_timestamps.csv
            └── drawings/
        └── Text/
            ├── text.csv
            └── text_final.txt
```

## 🛠️ Contributing

Feel free to open issues or pull requests to improve the app. Contributions are welcome!

---

## 📄 License

TODO

---

## ❤️ Acknowledgments

Thanks to the [goofi-pipe](https://github.com/dav0dea/goofi-pipe) team for providing the underlying data processing framework.
