# Tellius Forge - Standard Workflow

**Version:** v0.27.1
**For:** Blender 4.2–5.0 (tested on 5.0; minimum set to 4.2)  
**Covers:** Body (.gs) + Skeleton (.g) + Animation (.ga) import/export

---
## Videos
- In Blender: [Body & Skeleton Edits]()
- Outside Blender: [Texture and Simple Animation Edits]()
- In Blender: Detailed Animation Edits (TODO)

---
## 1. Blender Plugin Installation

1. In Blender, go to **Edit > Preferences > Add-ons**.
2. Click the dropdown arrow (**▼**) at the top-right and select **Install from Disk...**.
3. Navigate to `fe_plugin_current.py` and select it.
4. Search for "Fire Emblem" and check the box to enable it.
5. The plugin adds new options under **File > Import** and **File > Export**.

---

## 2. What You Can Import / Export in Blender

### Import

|Menu Item|What it Does|
|-|-|
|**FE9 & FE10 Body (.gs)**|**Imports just a .gs mesh file** — no skeleton, no skinning. Partial compatibility (some ymu & zmap).|
|**FE9 & FE10 Skeleton (.g)**|**Imports just a .g skeleton** as an armature. Partial compatibility (some ymu & zmap).|
|**FE9 & FE10 Body + Skeleton (.gs + .g)**|**Imports both skeleton and mesh** at once. The plugin auto-selects a matching .g file in the mesh's directory. Partial compatibility (some ymu & zmap).**This is the option you'll use most.**|
|**FE9 & FE10 Animation (.ga)**|**Imports animation files** onto an existing armature. Not fully compatible for all ymu skeletons or *yme* effects. Untested with *zu* battle animations. *See section 5.*|

When importing Body + Skeleton, the plugin names the armature after the model (e.g., `lord`), the armature data as `lord_skeleton`, and the mesh as `lord_body`.

### Export

|Menu Item|What it Does|
|-|-|
|**FE9 & FE10 Body (.gs)**|**Exports a single mesh object as .gs body.** The mesh must have been imported with this plugin first.|
|**FE9 & FE10 Skeleton (.g)**|**Exports an armature as .g skeleton.** Optionally takes a reference skeleton file for detecting new or modified data.|
|**FE9 & FE10 from Armature (.gs + .g)**|**Main export tool.** Select an armature and choose this export option. The plugin will export the armature and any children mesh modified by it. *See section 4e. Export for detailed description.*|
|**FE9 & FE10 Animation (.ga)**|**Export actions as .ga animation files.** You can export the single action on the active object, all actions in the blender file, or filter for multiple actions using keywords.|

---

## 3. Understanding the "Transform Pose"

Fire Emblem 9/10 skeleton files contain hard-coded transforms that aren't fully documented. Without these transforms, the mesh and bones may look disjointed or oddly positioned. When you import a model, the plugin will try to interpret the data and re-orient the mesh and bones to its expected transformed position. This is not always fully successful. **You may need to reset the positions when editing the mesh and skeleton for correct accumulation of position + transforms.**

To see the model in its disassembled rest pose:

1. Select the armature and enter **Pose Mode** (Ctrl+Tab, or use the mode dropdown).
2. Select all bones (**A**).
3. Reset transforms: **Alt+G** (location), **Alt+R** (rotation), **Alt+S** (scale).  
Or use **Pose > Clear Transform > All** from the menu.

This zeroes out the pose bones and shows where every body part naturally sits. The result often looks "broken" — limbs detached, body parts floating, etc.

> **Note:** We haven't documented all the hard-coded transforms yet. Some body parts may display oddly even after clearing transforms. If something looks wrong, try selecting individual bones in Pose Mode and resetting just their transforms.

---

## 4. Basic Workflow: Modify an Existing Model

### 4a. Import and Prep

1. **File > Import > FE9 & FE10 Body + Skeleton (.gs + .g).**  
Navigate to the model's folder (e.g., `ymu/pegasus/pack/`) and select `body.gs`. The plugin finds the matching skeleton automatically.
2. Open the **Shader Editor**. The necessary shaders were created upon import of a mesh.
3. Select slots to choose from different texture slots.
4. Load a png image in the *Image Texture Shader*. Extract png image textures from `.tpl` files using BrawlCrate.
5. Connect the nodes. Connect the *Image Texture* Color node to *Principled BSDF* Base Color.
6. Connect *Image Texture* Alpha node to *Mix Shader* Factor node.
7. If not already connected, connect BSDF nodes from *Principled BSDF* and *Transparent BSDF* to *Mix Shader* Shader nodes.
8. 

### 4c. Isolate Parts from the Add-on Model

1. Import a second model the same way. This will be referred to as an add-on model.
2. Select the mesh and enter **Edit Mode** (Press **Tab**, or use the mode dropdown).
3. Open the **Properties Editor** (usually bottom right) and navigate to the *Data Properties* tab. Its icon is a green outline of a triangle.
4. Use *Vertex Groups* to select/deselect parts of the body.
5. Delete all unwanted vertices of the body mesh.
6. Go back to **Object Mode**. Select the armature and enter **Edit Mode**.
7. Delete all unwanted bones.


### 4d. Combine Armatures
The goal is to have one armature and multiple meshes parented to it.  
**Do NOT use Ctrl+J (Join) on mesh files** — keep meshes as separate objects.


&emsp;<b>4d-i. Join Armatures</b>
1. Select the add-on armature (parent) THEN the main armature (parent). The order is important.  
2. Join the armatures (**Ctrl+J**). This will join the armatures into one, and make both mesh files children of the main armature.  
3. The add-on mesh no longer has an armature modifier, as its original armature is no longer available. Select the add-on mesh and go to *Modifiers* in the **Property Editor**. Input the main armature as the armature modifier's object.  
<br></br>

&emsp;<b>4d-ii. Edit Armature Bone Hierarchy</b>  
1. Select the armature and enter **Edit Mode**.  
2. Edit bone relations. Determine what equivalent bones existed in the original main armature and choose the same parent bones.  



### 4e. Position Add-On Model Parts

1. Enter **Pose Mode** with the armature still selected.
2. Reset transforms: **Alt+G** (location), **Alt+R** (rotation), **Alt+S** (scale). Or use **Pose > Clear Transform > All** from the menu.
3. Position the model using bone constraints (preferred) OR by moving the pose bones. It is difficult to predict skeleton-coded transforms if you use the second method.
4. Add/enable **Pose Bone Constraints** to force a bone to copy another bone's transform and position data. This will direct the plugin to copy bone record data upon skeleton export.  
>   - Select the bone you want to inherit transforms.  
>   - In the **Bone Constraints** tab, add a **Copy Location** constraint.  
>   - Set the `Target` to the armature and set the `Bone` to a corresponding source bone.

5. Select all bones with bone constraints. **Ctrl+A** and selec **Apply Visual Transform to Pose**  


### 4f. Save Updated Model Positions
1. Go back to **Object Mode**, select the add-on mesh and go to \\*Modifiers\\* in the **Property Editor**. Its icon is a wrench.
2. Duplicate the armature modifier and apply the duplicate.
3. Enter **Pose Mode** with the armature selected.
4. Open the Apply menu (**Ctrl+A**) and **Apply Pose as Rest Pose**.
5. Make sure to **keep each Pose Bone Constraint enabled** in **Pose Mode**. 
>- To enable the bone constraint, toggle the eye next to the bone constraint type so it is open and blue (not closed). 


### 4g. Export

1. Go to **Object Mode**, select the **armature** (not the mesh).
2. **File > Export > FE9 & FE10 Body + Skeleton from Armature (.gs + .g).**
3. In the file browser panel you'll see:

   * **Checkboxes for each mesh** — uncheck any you don't want included.
   * **Radio buttons** to choose which mesh is the "main" body (the one that was originally imported and has most of the `gs_original_data`). The main mesh provides the original chunk structure.
   * Other meshes become "addon" geometry (new chunks added to the file).
   * **Body Filename / Skeleton Filename** — what to name the output files. This defaults to body and skeleton, which is what all ymu model files must be named. File extensions will be appended if they are not included.
   * **Reference Skeleton** — input the path to the main original .g file for correct bone ordering. This should autofill based on data stored from the original import.
   * **Bone Order Options (2):** Choose whether to **incorporate added bones into the skeleton in Blender Hierarchy order**, or attempt to **preserve the original order with new bones appended**. Some skeletons may require the Blender Hierarchy order, though this will temporarily break all existing animations for the model.
   * **Vertex Color Options (3):** Vertex colors act as lighting multiplier. Leave as “*From Blender*” to use the original mesh’s lighting data (applied upon mesh import) or to use your own recolored Vertex Paint colors. Select “*White*” to set maximum lighting and "*None*" to use unmultiplied game lighting.
4. Click **Export** — the plugin writes both `.gs` and `.g` files.

---

## 5. Post-Blender Updates

1. Import any added textures to your model's tpl files using BrawlCrate.
2. Finalize material/texture data using the tool [gs-texture-edits.py](../tools/body/gs-texture-edits.py)
3. If your skeleton was exported using **Blender Hierarchy** bone order, update animations using the tool [ga-simple-edits](../tools/animation/ga-simple-edits).
>- Note: You must keep `../tools/ga-simple-edits/ga-simple-edits.py` and `../tools/ga-simple-edits/assets` in the same directory for the executable to function.


## 6. Animation Workflow (.ga)

### 6a. Copying Animations from a Reference Model

The standard method for giving a modified model animations from another model.

1. **Import modified and reference models.** Import your modified model (Body + Skeleton) plus one or two reference source models that have the animations you want.
2. **Apply the Armature and Pose Transforms** to all models.
    1. Click on the body object and open the **Modifier Propertes** tab (wrench icon in *Data Properties*). 
    2. **Duplicate the modified:** Click the dropdown arrow and select *Duplicate*. 
    3. **Apply the modifier**: Click the dropdown arrow on the duplicate modifier and select *Apply*. 
    4. Select the armature and enter Pose Mode. 
    5. Open the Apply menu (Ctrl+A) and select **Apply Pose as Rest Pose**. 
3. **Add pose bone constraints** on the modified model's armature. Use COPY_TRANSFORMS constraints targeting corresponding bones on a reference armature. This is how the animation data gets transferred.
4. **Import animation(s)** on the reference model(s): **File > Import > FE9 & FE10 Animation (.ga)**. Press **Space** in the 3D Viewport to pause/play the animation to verify it loaded correctly.
5. **Adjust playback timing** if needed. The animation's start/end frames are stored as custom properties on the action (Dope Sheet > Action Editor > Side Panel (press **N**) > Custom Properties. Look for *Start Frame* and *End Frame*). Set Blender's frame range to match.
6. **Enter Pose Mode** with the modified armature selected. The plugin already sets all pose bones to *XYZ Euler* rotation mode automatically during import.
7. **Select all bones** on the modified armature. **Bake action for rotation:** Pose > Animation > Bake Action...
    1. Check: *Selected Bones*, *Visual Keying*, *Overwrite Current Action*, *Clean Curves*. Keep *Frame Step* at 1. Confirm.
8. **Repeat Bake action** separately for **Location** and **Scale** (two more passes). You can bake on all bones, but it's more efficient to check the constraint target(s) to see which bones actually receive location/scale — usually just a few per type.
9. **Clean keyframes & channels:**
    1. In Pose Mode with all bones selected, open the **Graph Editor**. Make sure to enable sliders (View > Show Sliders) and Normalize (toggle button at top) so you can see the curves. 
    2. Select all channels (**A** in the left sidebar list), select all keyframes (**A** over the graph), then **Clean keyframes** (Key > Clean keyframes or press **X** and choose Clean). Leave threshold at default and check *Clean Channels*. 
    3. Click through the remaining channels with slider values near 0 and delete them if the curve is static. This removes unneccesary channels
    4. **Decimate rotation** (optional): If the baked curves are dense, reduce keyframe count with **Key > Decimate (Ratio)** at 30–50%. Be careful to avoid strong decimation that changes the curve shape (especially for location channels).

11. **Change the name of the baked action** before export. You cannot choose the name of the exported action(s) in the file dialog. Exported actions will use their name from blender. This allows for export of multiple actions.
12. **Export the animation:** *File > Export > FE9 & FE10 Animation {version} (.ga)*. The plugin reads the action's custom properties (*Start Frame*, *End Frame*, *ga_game_flag*, *ga_loop_flag*) and writes the .ga binary. See section 5c for per-action setup.

### 6b. Working on Multiple Animations

After baking one animation, repeat for the next:

1. **Save the action**: In the *Dope Sheet > Action Editor*, give it a name (include a prefix like the model name). Click the shield icon to add a "fake user" so Blender doesn't discard the action.
2. **Create a new action** for the modified armature: Use the dropdown in the Action Editor and click **New**.
3. **Switch animations** on the reference model(s) to the next desired .ga (select an action in the Action Editor dropdown).
4. **Change the playback range** to match the new animation's start/end frames.
5. **Clear all pose transforms** on all armatures: Select all armatures, enter Pose Mode, select all bones (**A**), then **Pose > Clear Transform > All** (or **Alt+G**, **Alt+R**, **Alt+S**).
6. **Repeat the baking steps** (6–10 from section 5a) for the new action.

### 6c. Animations from Scratch

> **Note**: Creating entirely new animations (not copied from an existing .ga) has had limited testing. The export should produce valid files, but in-game behaviour with footers, frame timing, and weapon-visibility channels is not yet confirmed. Always test exported animations in-game.

#### 6c-i. Setup

1. **Import your mesh+skeleton.** Ideally, you want a skeleton that has all 0x180 bone flags, as this is the most documented and consistent bone type. If you created the skeleton from scratch, all bones should meet this condition.
2. Organize your *Layout* workspace or switch to the *Animation* workspace. You will want open the *3D Viewport* and *Graph Editor* or *Dope Sheet*. I prefer to use the *Graph Editor*.
3. Select your armature (parent) and enter **Pose Mode**.
4. Open the *Playback Controls* either on the bottom of the *Dope Sheet* or the *Graph Editor*. There will be a small up arrow on the bottom right of the editor to open the *Playback Controls* if they are minimized.
5. **Set the start/end frames** of your animation. Animations generally start on frame 0 or 1. Set the End frame to a larger value, around 70-100 for character animations. You can adjust the timing later.
6. **Set the Active Keying Set** to Location, Rotation, Scale , or any combo of the three.
7. **Set the current frame** to a time where you want to establish a keyframe. Drag the frame marker or type the frame in Playback Controls.

#### **6c-ii. Insert Keyframes**

1. **Transform bones** in the 3D Viewport or in Bone Properties (green bone icon in the Data Property Editor).
2. **To insert a keyframe**: press **I** in the 3D Viewport or click on the dot/diamond on the right of the transform channel in Bone Properties.
3. Add as many keyframes as desired. Play the animation and adjust the keyframes and animation time until you are satisfied with the animation.

#### **6c-iii. Export**

1. Open the *Dope Sheet* and swap to view the *Action Editor*.
2. Press **N** to open the right side-panel. Expand the tabs “*FE Animation Export*” and “*Custom Properties*”. Custom properties should be empty.
3. Click the “**Prepare Action for Export**” button to generate custom properties needed for animation export. This is also available in the 3D Viewport’s Pose menu. The custom properties are described in the table below.

|Property|Description|
|-|-|
|*Start Frame*|First frame of the animation. Determined from imported animation or Playback scene data).|
|*End Frame*|Last frame of the animation. Determined from imported animation or Playback scene data.|
|*ga_game_flag*|`0` = FE9, `1` = FE10. Determined from imported animation or defaulted to 0 (FE9).|
|*ga_loop_flag*|`0` = non-loop, `1` = loop. Determined from imported .ga data or defaulted to 0 (non-looping).|

4. Verify that Start Frame and End Frame match your action’s timing. Change Game Flag and Loop flag values to 1 to set the game to  FE10 or enable looping behavior.
5. **Change the name of the action** before export. You cannot choose the name of the exported action(s) in the file dialog. Exported actions will use their name from blender. This allows for export of multiple actions.
6. **Export the animation** using the “*File > Export > FE9 & FE10 Animation {version_number} (.ga)*” option. You will export the one active action by default. There are options in the file dialog to export all actions or filter for multiple actions by partial matching name strings.
7. Most object animations or character animations do not need further editing. Some animations like attacking or moving require additional footer  data. Copy from a similar vanilla file and edit the timing. See <Tellius Animation File Format> for more info.

### 6e. Key Points

* **Footer data** (damage/effect timing, weapon visibility) is preserved verbatim for animations that have the original raw hex data available (stored as  `ga_raw_hex`). New/baked animations won't have footer data unless you manually construct it.
* **Decimation** reduces file size but changes f-curve values. Too much decimation may change the shape of f-curves.
* **Weapon visibility** in FE10 is often controlled in Footer Data 2, not standard bone animations. The plugin preserves footer data on round-trips but does not construct it for new animations.

---

## 7. Small Edits You Can Do

* **Rename a bone:** In Edit Mode on the armature, select a bone and rename it. The export preserves custom names.
* **Adjust UVs:** In Edit Mode on a mesh, select faces and use the UV editor. The export takes the mesh's current UV coordinates.
* **Apply fe_pose to Pose:** After importing, bones carry `fe_pose_location` / `fe_pose_rotation` custom properties. If you reset bone position, these transforms are still available. Select pose bones and use **Pose > Apply fe_pose to Pose** to transfer those values to the actual pose bone transforms.

---

## 8. Limitations & Things to Avoid

* **Don't delete vertices from the main model.** The export rebuilds the original chunk structure. Removing vertices can break display lists. If you want to hide something, make it invisible through modified animation, UVs, or textures.
* **Don't delete bones from the main armature.** The skeleton export and existing animations expects the original bones to exist in their original order. You can add new bones, but removing originals will likely cause errors.
* **Blender 4.2 minimum.** The plugin targets 4.2+ but has majorly been tested on 5.0.1 (one version check handles the fcurves API change).

