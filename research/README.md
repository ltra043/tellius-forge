# Research

Collection of reverse-engineering notes, technical documentation, and format analysis for assets from Fire Emblem: Path of Radiance (FE9) and Fire Emblem: Radiant Dawn (FE10).

Contains organized file format documentation, complete and in-progress research findings, theory notes, testing results, ImHex bookmarks, and other technical references created during development of the Tellius Forge Blender plugin. 

Documents are organized by asset type.

---

## Available Documents
**Status meanings:**
- **Complete:** Major findings verified through testing and considered stable.
- **Finalized:** Research is considered complete, though some conclusions rely on strong evidence rather than exhaustive testing.
- **Active Research:** Substantial findings available but some areas remain under investigation.
- **Preliminary:** Early findings with limited validation or sample coverage.

| Document | Asset | Status | Purpose |
|-----------|----|----|---------|
| [Tellius Animation File Format](./animation/tellius-animation-file-format.md) | animation | Complete | Reverse-engineered documentation of overworld `ymu` animation (`.ga`) files used by FE9 and FE10. |
| [FE9 Skeleton Flags](./skeleton/fe9-skeleton-flags.md) | skeleton | Finalized | Analysis of FE9 skeleton bone flags and Blender animation compatibility. |
| [FE10 Skeleton Flags](./skeleton/fe10-skeleton-flags.md) | skeleton | Preliminary | Analysis of FE10 skeleton bone flags and Blender animation compatibility. |
|  |  |  |  |