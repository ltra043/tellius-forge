# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


<!-- ## [Unreleased]

### Added

### Fixed

### Changed

### Removed -->

## [Unreleased]

### Added

### Fixed

### Changed

### Removed

## [0.2.0] - 2026-06-24

### Added

- Feature to `ga_simple_edits.py` and `ga-simple-edits.exe` allowing sorting of data by bone ID (ascending)
- Utility script `ga_sort_bones.py` to independently handle sorting of data by bone ID (ascending)
- CLI `-h` and `--help` code to provide information about tool scripts. Added to `ga_simple_edits.py`, `g_analyzer.py`, `ga_sort_bones.py`, and `ga_bookmark.py`.
- User-oriented `./docs/` files, including:
    - `animation-weapon-visibility-edits.md`
    - Updated `./docs/README.md`
- Research documents in `./research/`, including:
    - `tellius-body-file-format.md`
    - `tellius-skeleton-file-format.md`
    - Updated `./research/README.md`
- New images and gifs embedded in other files added to `./images/`
- Icons in png format with multiple color or transparent background fill options
- Transparent-background icons in ico format with [16x16, 32x32, 64x64, 128x128, 256x256] resolutions
- `CHANGELOG.md` in main to track all changes between releases
- Detailed installation instructions for Python and utility scripts to README.md

### Fixed

- Detection of dependent files in `ga_sort_bones.py` and `ga-simple-edits.exe`
- Code in `ga-simple-edits.py` to handle conflicting bone transforms
- Fixed missing module call for exit function (`exit` --> `sys.exit`) in `ga-simple-edits.py`
- Updated `requirements.txt` for `ga_sort_bones.py` and `gs_texture_edits.py`
- Various broken links, spelling, formatting

### Changed

- Utility scripts and subfolders in `./tools/` had their names changed to snake case. Python scripts and folders will be named using snake case from now on
- ga_sort_bones.py moved to `./tools/animation/ga_simple_edits/modules`
- Organized `./tools/` so main scripts and their dependencies are bundled together in the same directory
- Included dependent assets and modules in released toolkit `.exe` apps. External dependent files are no longer needed to run any `.exe`
- Icon for toolkit `.exe` apps


## [0.1.0] - 2026-05-30
This is the initial public release.

### Added
- Blender addon `tellius-forge.py`, internal version v0.27.1, in Releases
- Windows executable tools as `tellius-forge-toolkit.7z`, in Releases
    - Contains `gs-texture-edits.exe`, `ga-simple-edits.exe`, and  `ga-simple-edits.ui`
- Main `README.md` containing introduction, list of features, recommended starting points, compatibility & limitations, list of required downloads, Blender Add-on install instructions, repository structure tree, credits, license, disclaimer, and related search terms
- Blender plugin source code in `./plugin/`
- Utility tool source code in `./tools/`, including:
    - `ga-simple-edits` python script, ui file, and requirements
    - `ga-bookmark.py`
    - `gs-texture-edits` python script and requirements
    - `g-analyzer.py`
- User-oriented `./docs/` files, including:
    - `README.md` with About, Quick Start Guide, and table of all available documents
    - `getting-started.md`
    - `animation-compatibility.md`
    - `body-skeleton-workflow.md`
    - `animation-workflow.md`
- Research documents in `./research/`, including:
    - `README.md` with About section and table of all available research documents
    - `tellius-animation-file-format.md`
    - `fe9-skeleton-flags.md`
    - `fe10-skeleton-flags.md`
- Images and gifs embedded in all other files added to `./images/`


[unreleased]: https://github.com/ltra043/tellius-forge/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/ltra043/tellius-forge/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ltra043/tellius-forge/releases/tag/v0.1.0
