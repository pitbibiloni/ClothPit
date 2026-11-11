# AssetManagerPit

**User Documentation --- Version 1.0.0**\
**Author:** Pit Bibiloni\
**Declared compatibility:** Blender 5.2

AssetManagerPit combines two tools in a single add-on: asset assignment
to catalogs from the Asset Browser, and automatic texture connection for
FBX/OBJ models.

## 1. Installation

1.  Open Blender 5.2.
2.  Go to **Edit \> Preferences**.
3.  Open **Get Extensions** and choose **Install from Disk** (depending
    on your Blender setup, the add-on installation option may be located
    elsewhere in Preferences).
4.  Select `assetmanagerpit.py`.
5.  Enable the add-on if Blender does not enable it automatically.

The texture tool is available in the 3D Viewport Sidebar (`N`), under
the **AssetManagerPit** tab. The catalog tool is accessed from the Asset
Browser context menu.

## 2. Texture Connector

### 2.1 Importing models

There are two ways to import models:

-   **From the panel:** open the 3D Viewport, press `N`, and go to
    **AssetManagerPit \> Texture Connector**. Click **Import FBX / OBJ**
    and select one or more files.
-   **Drag and drop:** drag FBX or OBJ files into the 3D Viewport. The
    add-on's file handler imports the files and opens the texture
    confirmation dialog.

Multiple files can be imported in one operation, including files located
in different folders. The add-on stores the source folders for all files
in that import batch and selects the newly imported objects.

### 2.2 Confirming texture connection

After importing, a dialog appears:

> Do you wish to import associated textures in the folder?

When confirmed, the add-on searches each source folder and all its
subfolders for images. You do not need to select the texture folder
manually.

The **Connect Textures** button in the panel can be used to repeat the
search for the selected objects, using the folders recorded during the
most recent import.

### 2.3 Supported texture maps

  -----------------------------------------------------------------------
  Map type                            Connection
  ----------------------------------- -----------------------------------
  Base Color / Albedo / Diffuse /     Principled BSDF Base Color
  Color                               

  Roughness                           Principled BSDF Roughness

  Metallic / Metalness                Principled BSDF Metallic

  Normal                              Normal Map node connected to Normal

  AO / Occlusion                      Combined with Base Color using a
                                      Multiply mix

  Emission / Emissive                 Emission Color (or Emission,
                                      depending on the shader socket)

  Alpha / Opacity / Transparency      Principled BSDF Alpha

  Height / Displacement / Bump        Bump node connected to Normal
  -----------------------------------------------------------------------

Supported image formats: PNG, JPG/JPEG, TIF/TIFF, TGA, BMP, EXR, HDR,
and WEBP.

The add-on sets **sRGB** for Base Color and Emission, and **Non-Color**
for data maps such as Roughness, Metallic, Normal, AO, Alpha, and
Height.

### 2.4 Texture name recognition

The add-on analyzes image filenames and recognizes common terms and
abbreviations, including:

-   `BaseColor`, `Albedo`, `Diffuse`, `Color`, `D`
-   `Roughness`, `Rough`, `R`
-   `Metallic`, `Metalness`, `Metal`, `M`
-   `Normal`, `NormalGL`, `NormalDX`, `NRM`, `N`
-   `AO`, `Occlusion`
-   `Emission`, `Emissive`, `Emit`
-   `Opacity`, `Alpha`, `Transparency`
-   `Height`, `Bump`, `Displacement`

To select among candidate images, it compares the material name with the
texture filename. If there is no strong match and multiple candidates
exist, it also attempts to compare the object name.

**Recommendation:** although different naming conventions are supported,
using a shared identifier makes matching more reliable. For example:

``` text
SM_Rock_BaseColor.png
SM_Rock_Roughness.png
SM_Rock_Normal.png
SM_Rock_AO.png
```

### 2.5 Behavior and limitations

-   Models must be imported through the add-on's FBX/OBJ import
    operators.
-   The search is limited to the source folders from the most recent
    import and their subfolders.
-   **Connect Textures** operates on the currently selected objects. If
    no objects are selected, it cannot process their materials.
-   Each material is processed only once per operation, based on its
    name.
-   If multiple materials have generic names, or folders contain
    multiple textures of the same type without identifiable names,
    matching may be ambiguous.
-   AO is combined with Base Color only when the material has a
    connected Base Color texture.
-   The add-on does not guarantee recognition of every naming
    convention; it uses a built-in list of terms and abbreviations.

If the add-on reports **No maps could be connected**, check that the
imported objects are still selected, that the images are inside the
source folders or their subfolders, and that the filenames contain
recognizable map identifiers.

## 3. Asset Catalog Organizer

This tool assigns one or more selected assets to an existing catalog
from the Asset Browser context menu.

### 3.1 How to use it

1.  Open the **Asset Browser**.
2.  Select one or more assets.
3.  Right-click the selection.
4.  Choose **Assign to**.
5.  Select the destination catalog. Catalogs are displayed using their
    full paths, for example `Materials / Rock / Large`.
6.  Confirm the operation if Blender displays a confirmation prompt.

The add-on looks for the `blender_assets.cats.txt` file associated with
the asset library and lists the catalogs it finds there.

### 3.2 What it changes

The operation changes the catalog assigned to the selected assets in
their source `.blend` files. To do this, the add-on launches background
Blender processes, updates the asset datablocks, and saves the modified
source files. When finished, it attempts to refresh the asset library.

**Important:** this operation modifies and saves the original `.blend`
files in the library. Make a backup before assigning assets in batches.
Wait for the operation to finish before continuing to work with those
files.

### 3.3 Limitations

-   Online/remote assets are not supported.
-   Assets must belong to a local library whose source `.blend` file can
    be identified.
-   The destination catalog must already exist in that library's
    `blender_assets.cats.txt` file.
-   If a source file fails, the add-on reports the failure and
    recommends checking Blender's console.
-   The add-on does not create new catalogs; it assigns assets to
    existing catalogs.

## 4. Troubleshooting

  -----------------------------------------------------------------------
  Issue                               What to check
  ----------------------------------- -----------------------------------
  **Assign to** does not appear       Make sure you are in the Asset
                                      Browser and have selected assets.

  No catalogs are listed              Check that the library contains
                                      `blender_assets.cats.txt` and that
                                      catalogs are defined in it.

  Catalog assignment fails            Make sure the source `.blend` file
                                      exists and can be modified. Check
                                      the console for errors.

  The texture popup does not appear   Import using **Import FBX / OBJ**
                                      or drag FBX/OBJ files directly into
                                      the 3D Viewport.

  No images are found                 Check the model source folders and
                                      their subfolders, supported image
                                      formats, and map names.

  The wrong texture is connected      Use more specific and consistent
                                      material and texture names to avoid
                                      ambiguous matches.
  -----------------------------------------------------------------------

## 5. Feature Overview

  -----------------------------------------------------------------------
  Tool                    Location                Function
  ----------------------- ----------------------- -----------------------
  Texture Connector       3D Viewport \> `N` \>   Import FBX/OBJ files,
                          AssetManagerPit         search for textures,
                                                  and connect maps

  Asset Catalog Organizer Asset Browser context   Assign selected assets
                          menu                    to existing catalogs
  -----------------------------------------------------------------------

**AssetManagerPit --- Pit Bibiloni**\
Documentation version: 1.0.0 · Blender 5.2
