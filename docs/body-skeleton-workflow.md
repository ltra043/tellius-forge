# Body & Skeleton Workflow (.gs + .g)

**Written for Plugin Version:** v0.27.1
**For:** Blender 4.2–5.0 (tested on 5.0; minimum set to 4.2)  
**Covers:** Body (.gs) + Skeleton (.g) import, editing, and export

---
## Videos
- In Blender: [Body & Skeleton Editing](https://youtu.be/eqpfvmXnQCA)
- Outside Blender:  [Texture & Animation Setup](https://youtu.be/TF_WvlbTA4Q)

---

## 1. Basic Workflow: Modify an Existing Model

#### A. Import Body + Skeleton

1. **File > Import > FE9 & FE10 Body + Skeleton (.gs + .g).**  
Navigate to the model's folder (e.g., `ymu/pegasus/pack/`) and select `body.gs`. The plugin finds the matching skeleton automatically.

#### B. Load Textures (Optional)

Imported models do not automatically display textures. The following steps configure Blender materials so extracted textures can be previewed while editing.

1. Open the **Shader Editor**. The necessary shaders were created upon import of a mesh.
2. Select slots to choose from different texture slots.
3. Load a png image in the *Image Texture Shader*. Extract png image textures from `.tpl` files using BrawlCrate.
4. Connect the nodes. Connect the *Image Texture* Color node to *Principled BSDF* Base Color.
5. Connect *Image Texture* Alpha node to *Mix Shader* Factor node.
6. If not already connected, connect BSDF nodes from *Principled BSDF* and *Transparent BSDF* to *Mix Shader* Shader nodes.

#### C. Prepare the Add-on Model

1. Import a second model the same way. This will be referred to as an add-on model.
2. Select the mesh and enter **Edit Mode** (Press **Tab**, or use the mode dropdown).
3. Open the **Properties Editor** (usually bottom right) and navigate to the *Data Properties* tab. Its icon is a green outline of a triangle.
4. Use *Vertex Groups* to select/deselect parts of the body.
5. Delete all unwanted vertices of the body mesh.
6. Go back to **Object Mode**. Select the armature and enter **Edit Mode**.
7. Delete all unwanted bones.


#### D. Combine Armatures
The goal is to have one armature and multiple meshes parented to it.  
> **IMPORTANT**
>- **Do NOT use Ctrl+J (Join) on mesh files** 
> - Keep meshes as separate objects.
> - Tellius Forge exporting expects separate mesh objects for added geometry.


1. **Join Armatures**
   1. Select the add-on armature (parent) THEN the main armature (parent). The order is important.  
   2. Join the armatures (**Ctrl+J**). This will join the armatures into one, and make both mesh files children of the main armature.  
   3. The add-on mesh no longer has an armature modifier, as its original armature is no longer available. Select the add-on mesh and go to *Modifiers* in the **Property Editor**. Input the main armature as the armature modifier's object.  

2. **Edit Armature Bone Hierarchy**
   1. Select the armature and enter **Edit Mode**.  
   2. Edit bone relations. Determine what equivalent bones existed in the original main armature and choose the same parent bones.  


#### E. Position Add-On Model Parts

1. Enter **Pose Mode** with the armature still selected.
2. Reset transforms: **Alt+G** (location), **Alt+R** (rotation), **Alt+S** (scale). Or use **Pose > Clear Transform > All** from the menu.
3. Position the model using bone constraints (preferred) OR by moving the pose bones. It is difficult to predict skeleton-coded transforms if you use the second method.
4. Add/enable **Pose Bone Constraints** to force a bone to copy another bone's transform and position data. This will direct the plugin to copy bone record data upon skeleton export.  
   1. Select the bone you want to inherit transforms.  
   2. In the **Bone Constraints** tab, add a **Copy Location** constraint.  
   3. Set the `Target` to the armature and set the `Bone` to a corresponding source bone.

5. Select all bones with bone constraints. **Ctrl+A** and select **Apply Visual Transform to Pose**  


#### F. Save Updated Model Positions
1. Go back to **Object Mode**, select the add-on mesh and go to \\*Modifiers\\* in the **Property Editor**. Its icon is a wrench.
2. Duplicate the armature modifier and apply the duplicate.
3. Enter **Pose Mode** with the armature selected.
4. Open the Apply menu (**Ctrl+A**) and **Apply Pose as Rest Pose**.
5. Make sure to **keep each Pose Bone Constraint enabled** in **Pose Mode**. 
   1. To enable the bone constraint, toggle the eye next to the bone constraint type so it is open and blue (not closed). 


#### G. Export

1. Go to **Object Mode**, select the **armature** (not the mesh).
2. **File > Export > FE9 & FE10 Body + Skeleton from Armature (.gs + .g).**
3. In the file browser panel you'll see:

   * **Checkboxes for each mesh** — uncheck any you don't want included.
   * **Radio buttons** to choose which mesh is the "main" body (the one that was originally imported and has most of the `gs_original_data`). The main mesh provides the original chunk structure.
   * Other meshes are exported as **add-on geometry** (new chunks added to the file).
   * **Body Filename / Skeleton Filename** — what to name the output files. This defaults to body and skeleton, which is what all ymu model files must be named. File extensions will be appended if they are not included.
   * **Reference Skeleton** — input the path to the main original .g file for correct bone ordering. This should autofill based on data stored from the original import.
   * **Bone Order Options (2):** Choose whether to **incorporate added bones into the skeleton in Blender Hierarchy order**, or attempt to **preserve the original order with new bones appended**. Some skeletons may require the Blender Hierarchy order, though this will temporarily break all existing animations for the model.
   * **Vertex Color Options (3):** Vertex colors act as lighting multiplier. Leave as “*From Blender*” to use the original mesh’s lighting data (applied upon mesh import) or to use your own recolored Vertex Paint colors. Select “*White*” to set maximum lighting and "*None*" to use unmultiplied game lighting.
4. Click **Export** — the plugin writes both `.gs` and `.g` files.

---

## 2. Game File Updates
Update body.gs material and texture data if you added textures. 

Update animation data if you inserted new bone(s) using Blender Hierarchy export mode.

1. Download `tellius-forge-toolkit.7z` from the [latest release](https://github.com/ltra043/tellius-forge/releases/latest).
2. Import any added textures to your model's tpl files using BrawlCrate.
3. Finalize material/texture data using the tool `gs-texture-edits.exe`
4. If your skeleton was exported using **Blender Hierarchy** bone order, update animations using the tool `ga-simple-edits`.
   1. **Important Note:** You must keep `ga-simple-edits.exe` and `assets/` in the same directory for the executable to function.


---

## 3. Modification Ideas

* **Add weapons, minor geometry, or swap faces**: add mesh to customize models or give new weapons.  
* **Rename a bone:** In Edit Mode on the armature, select a bone and rename it. The export preserves custom names.
* **Adjust UVs:** While in Edit Mode on a mesh, view UVs using the UV Editor. Select faces and transform UVs. Press **V** to rip UVs from linked seams.

---

## 4. Limitations & Things to Avoid

* **Don't delete vertices from the main model.** The export rebuilds the original chunk structure. Removing vertices can break display lists. If you want to hide something, make it invisible through modified animation, UVs, or textures.
* **Fully custom models are not currently supported.** However, custom geometry can be added as an add-on mesh and exported alongside a supported base model.
   - The main mesh can be made invisible to functionally allow creation of custom meshes. 
   - The main mesh can be extremely simple. I recommend `wave_99.gs` from FE9 `bmap02`. 
* Some objects may experience **backface culling**. Mesh should be tested in-game to determine if it needs to be edited to counteract backface culling.
* **Blender 4.2 minimum.** The plugin targets 4.2+ but has majorly been tested on 5.0.1 (one version check handles the fcurves API change).

