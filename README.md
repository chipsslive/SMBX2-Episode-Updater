# SMBX2 Episode Updater

A user-friendly application for automatically updating SMBX2 (Super Mario Bros. X2) episodes. Features both a graphical interface and command-line tools for downloading, extracting, and merging episode (or entirely fresh installs!) while preserving save files and user data.

## Quick Start

### Before You Launch

You will be prompted to provide the path to the SMBX2 episodes directory when you first start the updater. This can be found at the directory `data/worlds` from the root of your SMBX2 install. If you do not have SMBX2, you can download it at https://codehaus.moe/.

### Launching the Updater

**Option 1: Download Pre-built Executable**
- Download the latest release from the [Releases](../../releases) page
- Extract and run `SMBX2 Episode Updater.exe` (Windows)
- No Python installation required!

**Option 2: Run from Source**
```bash
# Clone the repository
git clone https://github.com/chipsslive/SMBX2-Episode-Updater.git
cd SMBX2-Episode-Updater

# Install dependencies
pip install -r requirements.txt

# Run the GUI
python src/gui.py

# Or use the command line
python src/smbx2_episode_updater.py --help
```

## Caveats

- **URL**: The URL provided for the episode download must lead directly to a `.zip` file. This means that things like a Google Drive link (AKA a link to a page housing a file, rather than a link to the file itself) will not work with this application. The episode distributor is expected to host the file through something like a CDN (Content Distribution Network) for direct access to the file address.
- **Folder Naming**: The episode folder name inside the downloaded ZIP file for a given episode must be identical every time it is updated. For example, if you name your episode folder for your first release `My Episode`, then it must be named `My Episode` for every subsequent update. When checking for folders to merge the downloaded files with in the episodes directory, the application checks against the name of the highest-level folder in the extracted ZIP that houses a `.wld` file. This is how it identifies the root directory of episodes. If it can't find a matching name, it will just create a fresh install of the episode.

## Command Line Usage

The CLI tool (`ctl`) provides full functionality for automation and advanced users:

### Initialize Configuration
```bash
python src/smbx2_episode_updater.py init \
  --episodes-dir "C:\SMBX2\data\worlds" \
  --episode-url "https://example.com/episode.zip"
```

### Update Episode
```bash
python src/smbx2_episode_updater.py update
```

### Check Remote Version
```bash
python src/smbx2_episode_updater.py check
```

### Update Configuration
```bash
# Change episode URL
python src/smbx2_episode_updater.py set-url --episode-url "https://new-url.com/episode.zip"

# Change episodes directory
python src/smbx2_episode_updater.py set-dir --episodes-dir "C:\New\Path\episodes"
```

### View Current Settings
```bash
python src/smbx2_episode_updater.py show
```

### All Available Commands
```bash
python src/smbx2_episode_updater.py --help
```

## Building from Source

### Prerequisites
- Python 3.9 or higher
- pip package manager

### Install Dependencies
```bash
pip install requests tqdm pyinstaller
```

### Build Executable

**Single Folder Build**:
```bash
python -m PyInstaller --noconfirm --name "SMBX2 Episode Updater" --paths src src/gui.py
```

**Single File Executable Build (Slower)**:
```bash
python -m PyInstaller --noconfirm --onefile --name "SMBX2 Episode Updater" --paths src src/gui.py
```

Built executables will be in the `dist/` directory.

## Configuration

The application stores configuration and state in a `user_data/` directory:

- `user_data/config.json`: Episode directory and download URL settings
- `user_data/state.json`: Last update information and installed version
- `user_data/cache/`: Downloaded files and extraction staging area
- `user_data/cache/backups/`: Automatic backups of previous installations

### Preserved Files

By default, these file patterns are preserved during updates:
- `save*-ext.dat` - Extended save data
- `save*.sav` - 1.3 save files  
- `progress.json` - Achievement tracking

These can be manually modified via the `preserve_globs` field in `user_data/config.json` (generated on first run).

## Logging

The application includes logging about file operations, download progress, and error details to help diagnose issues:

**Log Files Location**: `logs/SMBX2EpisodeUpdater.log` (rotated, 10MB max, 5 backups)

## Requirements

- **Python**: 3.9+
- **Dependencies**: 
  - `requests` >= 2.31 (HTTP downloads)
  - `tqdm` >= 4.66 (Progress bars)
- **SMBX2**: Designed for SMBX2 folder structure (download at https://codehaus.moe/)

## License/Support

- **Usage**: This project is open source. Do whatever you want with it.
- **Issues**: Report bugs and feature requests in the [Issues](../../issues) section
