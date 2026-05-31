# Getting Started

## 1. Before You Begin

You will  need:
- Blender 4.2+
- Tellius Forge
- Extracted FE9/FE10 assets
- BrawlCrate (for texture work)

## 2. Blender Plugin Installation

1. Download `tellius-forge.py` from the [latest release of Tellius Forge](https://github.com/ltra043/tellius-forge/releases/latest)
2. In Blender, go to **Edit > Preferences > Add-ons**.
3. Click the dropdown arrow (**▼**) at the top-right and select **Install from Disk...**.
4. Navigate to `tellius-forge.py` and select it to install.
5. Search for "Tellius Forge" and check the box to enable it.
6. The plugin adds new options under **File > Import** and **File > Export**.

## 3. What You Can Import / Export in Blender

### Import

|Menu Item|What it Does|
|-|-|
|**FE9 & FE10 Body (.gs)**|**Imports just a .gs body file** as a mesh. No skeleton, no skinning. Partial compatibility (some `ymu` & `zmap`).|
|**FE9 & FE10 Skeleton (.g)**|**Imports just a .g skeleton** as an armature. Partial compatibility (some `ymu` & `zmap`).|
|**FE9 & FE10 Body + Skeleton (.gs + .g)**|**Imports both the body and skeleton** at once. The plugin automatically searches for a corresponding `.g` file in the selected mesh's directory. Partial compatibility (some `ymu` & `zmap`). **This is the option you'll use most.**|
|**FE9 & FE10 Animation (.ga)**|**Imports animation files** onto an existing armature. Not fully compatible for all `ymu` skeletons or `yme` effects. Untested with `zu` battle animations. *See [Animation Compatibiilty](./animation-compatibility.md) for list of compatible models.* |

When importing Body + Skeleton, the plugin names the armature after the model (e.g., `lord`), the armature data as `lord_skeleton`, and the mesh as `lord_body`.

### Export

|Menu Item|What it Does|
|-|-|
|**FE9 & FE10 Body (.gs)**|**Exports a single mesh object as .gs body.** The mesh must have been imported with this plugin first.|
|**FE9 & FE10 Skeleton (.g)**|**Exports an armature as .g skeleton.** Optionally takes a reference skeleton file for detecting new or modified data.|
|**FE9 & FE10 Body + Skeleton from Armature (.gs + .g) **|**Main export tool.** Select an armature and choose this export option. The plugin will export the armature and any children mesh modified by it. *See [Body & Skeleton Workflow](./body-skeleton-workflow.md) for detailed export description.*|
|**FE9 & FE10 Animation (.ga)**|**Export actions as .ga animation files.** You can export the single action on the active object, all actions in the blender file, or filter for multiple actions using keywords.|

## 4. Understanding the "Transform Pose"

Fire Emblem 9/10 skeleton files contain hard-coded transforms that aren't fully documented. Without these transforms, the mesh and bones may look disjointed or oddly positioned. 

When you import a model, the plugin will try to interpret the data and re-orient the mesh and bones to its expected transformed position. This is not always fully successful. 

**You may need to clear these transforms before editing body and skeleton assets. Editing and export behavior are more predictable when the body and skeleton are returned to their original, untransformed positions.**

To see the model in its disassembled rest pose:

1. Select the armature and enter **Pose Mode** (Ctrl+Tab, or use the mode dropdown).
2. Select all bones (**A**).
3. Reset transforms: **Alt+G** (location), **Alt+R** (rotation), **Alt+S** (scale).  
Or use **Pose > Clear Transform > All** from the menu.

This zeroes out the pose bones and shows where every body part naturally sits. The result often looks "broken" — limbs detached, body parts floating, etc.

> **Note:** We haven't documented all the hard-coded transforms yet. Some body parts may display oddly even after clearing transforms. If something looks wrong, try selecting individual bones in Pose Mode and resetting just their transforms.

## 5. Navigating Blender
<details>

<summary>
Blender Concepts Used Throughout This Documentation
</summary>


#### A. Menus
Unless a keyboard shortcut is mentions, "menu" refers to the horizontal bars at the top of the area or the collective window. It may refer to the Editor menu or to the Blender menu.
#### B. Editors and  Areas
1. **Areas** are the container spaces. 
    1. They are "where" you work and view information.
2. **Editors** are the digital tool displayed in an area. 
    1. They are "what" tool or interface is being used. 
    2. Editors can be swapped out using the leftmost dropdown in an area's menu.
#### C. Workspaces
Workspaces are the arrangement of areas and editors on the screen. You can have different presets for different workspaces. 
1. You should always have open:
    1. **Outliner** set to *View Layer* mode (upper-right)
    2. **Data Properties** (lower-right) open. These are typically open by default.
2. You will most frequently use **Layout** for body/skeleton editing and **Animations** for animation editing.
    1. **Layout** editors: 
        - **3D Viewport** (main upper-left)
        - **Shader Editor** (lower-left)
    2. **Animation** editors: 
        - **Graph Editor** (main bottom)
        - **Dope Sheet** set to view *Action Editor* (upper-left)
        - **3D Viewport** (upper-right) 
#### D. Work Modes
1. **Object Mode:** for selecting and modifying entire objects (armature or mesh). You must be in Object Mode to select a different object.
2. **Edit Mode:** View and edit the *actual state* of an object. 
    1. Press **Tab** from the other two modes to enter Edit Mode.
    2. Armatures in Edit Mode: 
        - Modify actual Bone Position without influencing the body mesh. 
        - Edit bone relations 
        - View custom properties like fe_bone_flag and fe_bone_index.
    3. Mesh in Edit Mode:
        - Select and manipulate parts of the mesh (vertices, edges, faces).
        - View Vertex Groups to understand which parts of the body are skinned to each bone. 
        - View and experiment with assigning texture per Vertex Group
        - Modify UVs in the UV Editor
3. **Pose Mode (armature only):** Apply transforms to pose bones to "pose" the model. This does not change the "actual" position or scale of bones or mesh.
    1. Press **Ctrl+Tab** to toggle between Object Mode and Pose Mode.
    2. Apply Pose Bone Transforms in **Bone Properties** in the **Data Properties** Editor.
    3. Clear Pose bone Transforms in the Pose menu > Clear Transforms > All or use keyboard shortcuts **Alt+S**, **Alt+R**, and **Alt+G**.
    4. Create **Pose Bone Constraints** to temporarily copy specified transforms or properties from one bone to another.
    5. Custom pose menu action to "Apply fe_pose to pose". This re-applies skeleton-data-based pose transforms on selected bone(s).
    6. View and edit per-bone animation f-curves in the **Graph Editor** in Pose Mode.

</details>


## 6. Next Steps

After installing the plugin and becoming familiar with the import/export options, continue with:

- [Body & Skeleton Workflow](./body-skeleton-workflow.md)