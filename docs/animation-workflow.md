# Animation Workflow (.ga)

**Written for Plugin Version:** v0.27.1
**For:** Blender 4.2–5.0 (tested on 5.0; minimum set to 4.2)  
**Covers:** Blender animation import, editing, creation, retargeting, and export

---
## Videos
- In Blender: Detailed Animation Edits(TODO)
- Animation File Format (TODO)
---

## 1. Copying Animations from a Reference Model

The goal of this workflow is to transfer animation from a reference model onto a modified model by using Blender constraints and baking the resulting motion.

#### A. Prepare models for animation

1. **Import modified and reference models.** Import your modified model (Body + Skeleton) plus one or two reference source models that have the animations you want.
2. **Apply the Armature and Pose Transforms** to all models.
    1. Click on the body object and open the **Modifier Properties** tab (wrench icon in *Data Properties*). 
    2. **Duplicate the modified:** Click the dropdown arrow and select *Duplicate*. 
    3. **Apply the modifier**: Click the dropdown arrow on the duplicate modifier and select *Apply*. 
    4. Select the armature and enter Pose Mode. 
    5. Open the Apply menu (Ctrl+A) and select **Apply Pose as Rest Pose**. 
3. **Add pose bone constraints** on the modified model's armature. Use COPY_TRANSFORMS constraints targeting corresponding bones on a reference armature. This is how the animation data gets transferred.

#### B. Import animations
1. **Import animation(s)** on the reference model(s): **File > Import > FE9 & FE10 Animation (.ga)**. Press **Space** in the 3D Viewport to pause/play the animation to verify it loaded correctly.
2. **Adjust playback timing** if needed. The animation's start/end frames are stored as custom properties on the action 
    1. Navigate to Dope Sheet > Action Editor > Side Panel (press **N**) > Custom Properties. 
    2. Look for *Start Frame* and *End Frame*. 
    3. Set Blender's frame range to match.
3. **Enter Pose Mode** with the modified armature selected. 

#### C. Bake Action
1. Verify that bone rotation mode is set to *XYZ Euler* for bones. The plugin should set this mode automatically after importing animations.
2. **Select all bones** on the modified armature. **Bake action for rotation:** Pose > Animation > Bake Action...
    1. Options to enable with checkbox: 
        - *Selected Bones*
        - *Visual Keying*
        - *Overwrite Current Action*
        - *Clean Curves*
    2. Keep *Frame Step* set to 1. 
    3. Confirm to bake the action.
3. **Repeat Bake action** separately for **Location** and **Scale** (two more passes). 
    1. You can bake on all bones, but it's more efficient to check the constraint target(s) to see which bones actually receive location or scale transforms. It is usually just a few per type.
4. **Clean keyframes & channels:**
    1. In Pose Mode with all bones selected, open the **Graph Editor**. Make sure to enable sliders (View > Show Sliders) and Normalize (toggle button at top) so you can see the curves. 
    2. Select all channels (press **A** in the left sidebar list), select all keyframes (press **A** over the graph), then **Clean keyframes** (*Key > Clean keyframes*). Leave threshold at default and check **Clean Channels**. 
    3. Click through the remaining channels with slider values near 0 and delete them if the curve is static. This removes unneccesary channels.
    4. **Decimate rotation** (optional): If the baked curves are dense, reduce keyframe count with **Key > Decimate (Ratio)** at 30–50%. Be careful to avoid strong decimation that changes the curve shape (especially for location channels).
#### D. Export the animation
1. **Change the name of the baked action** before export. 
    1. You cannot choose the name of the exported action(s) in the file dialog. Exported actions will use their name from blender. This allows for export of multiple actions.
2. **Export the animation:** *File > Export > FE9 & FE10 Animation {version} (.ga)*. 
    1. The plugin reads the action's custom properties (*Start Frame*, *End Frame*, *ga_game_flag*, *ga_loop_flag*) and writes the .ga binary. 

---

## 2. Working on Multiple Animations

#### A. Prepare Actions
After baking one animation, repeat for the next:

1. **Save the action**: In the *Dope Sheet > Action Editor*, give it a name (include a prefix like the model name). Click the shield icon to add a "fake user" so Blender doesn't discard the action.
2. **Create a new action** for the modified armature: Use the dropdown in the Action Editor and click **New**.
3. **Switch animations** on the reference model(s) to the next desired .ga (select an action in the Action Editor dropdown).
4. **Change the playback range** to match the new animation's start/end frames.
5. **Clear all pose transforms** on all armatures: Select all armatures, enter Pose Mode, select all bones (**A**), then **Pose > Clear Transform > All** (or **Alt+G**, **Alt+R**, **Alt+S**).
6. **Repeat the baking steps** (*see section 1C*) for the new action.

#### B. Export multiple actions as animations
1. Make sure to all actions you want to export belong to the same model. 
2. Include a **characteristic string** in the name of each action you want to export.
    1. I suggest using the name of the model. Use names formatted like: `lord - wait_sw` or `fighter - atk2_HA`
3. Select the armature of the model. 
4. Select **File > Export > FE9 & FE10 Animation {version} (.ga)**
5. Use literal strings or regular expressions to search for the **characteristic string** identifying the actions you want to export.
    1. In the export UI, the search textbox is on the right panel.
    2. After typing, you should be able to see a list of actions that will be exported.
6. Alternatively, use the checkbox option to **Export All Actions** present in the Blender scene. 
    1. Only use this option if all actions apply to the same armature.

---
## 3. Animations from Scratch

> **Note**: Creating entirely new animations (not copied from an existing .ga) has had limited testing. The export should produce valid files, but in-game behaviour with footers, frame timing, and variable bone flags is not yet confirmed. Always test exported animations in-game.

#### A. Setup

1. **Import your mesh+skeleton.** 
    1. Ideally, you want a skeleton that has all 0x180 bone flags, as this is the most documented and consistent bone type. 
    2. New bones created through Tellius Forge export default to this 0x180 bone flag. 
    3. Bone Constraint export behavior overrides this 0x180 bone flag default and instead copies the bone flag of the constraint target.
2. Organize your *Layout* workspace or switch to the *Animation* workspace. 
    1. You will want open the *3D Viewport* and *Graph Editor* or *Dope Sheet*. I prefer to use the *Graph Editor*.
3. Select your armature (parent) and enter **Pose Mode**.
4. Open the *Playback Controls* either on the bottom of the *Dope Sheet* or the *Graph Editor*. 
    1. There will be a small up arrow on the bottom right of the editor to open the *Playback Controls* if they are minimized.
5. **Set the start and end frames** of your animation. 
    1. Animations generally start on frame 0 or 1. 
    2. Set the End frame to a larger value, around 30-80 for most character animations. You can adjust the timing later.
6. **Set the Active Keying Set** to Location, Rotation, Scale , or any combo of the three.
7. **Set the current frame** to a time where you want to establish a keyframe. Drag the frame marker or type the frame in Playback Controls.

#### B. Insert Keyframes

1. **Transform bones** in the *3D Viewport* or in *Bone Properties* (green bone icon in the Data Property Editor).
2. **To insert a keyframe**: press **I** in the *3D Viewport* or click on the dot/diamond on the right of the transform channel in *Bone Properties*.
3. Add as many keyframes as desired. 
4. Play the animation and adjust the keyframes and animation time until you are satisfied with the animation.

#### C. Export

1. Open the *Dope Sheet* and swap to view the *Action Editor*.
2. Press **N** to open the right side-panel. Expand the tabs “*Tellius Forge*” and “*Custom Properties*”. Custom properties should be empty.
3. Click the “**Prepare Action for Export**” button in "*Tellius Forge*". 
    1. This generates the custom properties required by the exporter. Newly created actions will not contain these properties by default.
    2. This is also available in the 3D Viewport’s Pose menu. 
    3. The custom properties are described in the table below.

|Property|Description|
|-|-|
|*Start Frame*|First frame of the animation. Determined from imported animation or Playback scene data.|
|*End Frame*|Last frame of the animation. Determined from imported animation or Playback scene data.|
|*ga_game_flag*|`0` = FE9, `1` = FE10. Determined from imported animation or defaulted to 0 (FE9).|
|*ga_loop_flag*|`0` = non-loop, `1` = loop. Determined from imported .ga data or defaulted to 0 (non-looping).|

4. Verify that Start Frame and End Frame match your action’s timing. 
5. You may change **game flag** and **loop flag** values to 1 to set the game to  FE10 or enable looping behavior.
6. **Change the name of the action** before export. 
    1. You cannot choose the name of the exported action(s) in the file dialog. Exported actions will use their name from blender. This allows for export of multiple actions.
7. **Export the animation** using the “*File > Export > FE9 & FE10 Animation {version_number} (.ga)*” option. 
    1. You will export the one active action by default. 
    2. There are options in the file dialog to export all actions or filter for multiple actions by partial matching name strings.
8. Most object animations or character animations do not need further editing. Some animations like attacking or moving require additional footer  data. Copy from a similar vanilla file and edit the timing. See [Tellius Animation File Format](../research/animation/Tellius%20Animation%20File%20Format.md) for more info.
---
## 4. Other factors to consider

#### A. Footer Data 1 (Effect Timing)
Footer data is preserved verbatim for animations that have the original raw hex data available (stored as  `ga_raw_hex`). 

New/baked animations won't have footer data unless you manually construct it.


> **Common Symptom**
>
> If an exported animation **unexpectedly loops** and lacks gameplay behavior (hit timing, effects, etc.), **missing or incorrectly formatted Footer Data 1** is often the cause.

#### B. Footer Data 2 (Weapon Visibility)
Weapon visibility in FE10 is often controlled in Footer Data 2, not standard bone animations. The plugin preserves footer data on round-trips but does not construct it for new animations. 

You can construct Footer Data 2 or set `scale = 0` for invisible weapons using animation transformations.