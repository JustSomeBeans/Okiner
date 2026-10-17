# Feature Specification & Refactoring Plan: Okiner Bot Updates

## 1. Overview & Objectives

This document provides step-by-step technical instructions for upgrading the **Okiner** bot system. The update introduces two major enhancements:

1. **New Case Combination Mode**: Expansion of the `/addrp` modal/mode toggle to include a 4th operational mode: `Standard Case + Self Case + Null Case`.
2. **Native Image Upload Support with Dynamic Validation**: Updating `/addrp` and the rendering pipeline to allow users to directly attach image files (via Discord `Attachment`) *or* provide a URL link to a third-party image host, while ensuring strict mutual exclusivity and backwards compatibility.

---

## 2. Feature 1: Case Mode Expansion

### Current Modes
Currently, the RP creation flow supports three toggles:
* `Standard Case`
* `Standard Case + Null Case`
* `Standard Case + Self Case`

### Requirement
Add a fourth configurable mode:
* **`Standard Case + Self Case + Null Case`** (combines standard payload calculation, self-referential case handling, and null-state fallbacks).

### Implementation Steps
1. **Enum / Choice Update**:
   * Update the slash command choice parameter for `mode` (or modal drop-down) in the `/addrp` definition to include:
     * Label: `Standard + Self + Null`
     * Value: `standard_self_null` (or integer representation matching current enum convention).
2. **Database Schema & Enums**:
   * Ensure the mode column in the database schema accepts the new state value.
3. **RP Resolution Engine Update**:
   * Update the execution handler where cases are evaluated during RP generation/calculation:
     ```python
     if mode == Mode.STANDARD_SELF_NULL:
         # Execute Standard logic
         # Apply Self-case transformations
         # Fallback to Null-case handling if variables/evaluations resolve to null
     ```

---

## 3. Feature 2: Dual Image Input (Direct Upload vs. Hosted Link)

To improve user experience while maintaining complete backwards compatibility, users must be able to either submit a hosted URL or attach an image file directly when running `/addrp`.

### 3.1 Slash Command Definition & Pre-Modal Validation

Discord modals do not natively support file upload inputs directly inside modal forms. Therefore, image attachments must be handled via the initial Slash Command parameters prior to modal trigger/interaction.

#### Command Parameters for `/addrp`
* `image_file` (`discord.Attachment`, **Optional**): Direct file upload attachment.
* `image_url` (`str`, **Optional**): URL pointing to a 3rd party image host.
* *(Additional command parameters as configured)*

#### Input Validation Logic (XOR Constraint)
Before opening the submission form or creating the database record, validate that **exactly one** of these two inputs is provided:

```python
# Validation condition: Exactly one field must be populated
has_file = image_file is not None
has_url = image_url is not None and len(image_url.strip()) > 0

if not (has_file ^ has_url):  # Logical XOR check
    if not has_file and not has_url:
        await interaction.response.send_message(
            "❌ **Error:** You must provide either an **image upload** OR an **image link**.",
            ephemeral=True
        )
        return
    else:
        await interaction.response.send_message(
            "❌ **Error:** You cannot provide both an image upload and a link. Please choose only one option.",
            ephemeral=True
        )
        return
```

---

### 3.2 Image Handling & Database Architecture

To ensure local attachments persist reliably (since Discord CDN links for ephemeral attachments can expire or be invalidated), uploaded files must be ingested or linked to permanent storage/CDN URLs.

#### Database Changes
Ensure the image storage column (e.g., `image_data` or `image_url`) is flexible:
* Schema type: `TEXT`
* Content format:
  * For third-party URLs: Raw string URL (e.g., `https://i.imgur.com/example.png`)
  * For direct Discord attachments: Store the permanently proxy-hosted URL or local database path/blob reference.

#### Processing Workflow:
1. **If `image_url` is provided**:
   * Sanitize and validate URL format (e.g., regex check for `http://` or `https://`).
   * Store directly into `image_data` DB column.
2. **If `image_file` is provided**:
   * Verify attachment content type (`image/png`, `image/jpeg`, `image/webp`, `image/gif`).
   * Retrieve the attachment URL (`image_file.url` or save locally/to attachment storage service if local hosting is configured).
   * Store the resolved image URI into `image_data` DB column.

---

### 3.3 Embed Renderer Updates (Backwards Compatibility)

The rendering pipeline that generates RP cards/embeds must remain agnostic to where the image originated.

#### Resolution Steps:
1. Fetch `image_data` string from the database.
2. Determine if the value represents:
   * A web URL (`http://` / `https://`)
   * A local database/file path reference
3. **Embed Attachment logic**:
   * **For Web/CDN URLs**: Pass directly to `embed.set_image(url=image_data)`.
   * **For Local/Stored Assets**: If local database file storage is used, construct a `discord.File` object and attach it to the message payload, referencing `attachment://filename.png` in `embed.set_image(url=...)`.

---

## 4. Verification & Testing Checklist

- [ ] **Mode Expansion**: Verify `/addrp` presents `Standard + Self + Null` mode option and correctly routes through the case solver engine.
- [ ] **Validation - No Inputs**: Test `/addrp` with neither `image_file` nor `image_url`. Confirm ephemeral error stops the workflow.
- [ ] **Validation - Dual Inputs**: Test `/addrp` with both an attached image file AND a URL link. Confirm ephemeral error stops the workflow.
- [ ] **Validation - Single Input (Upload)**: Test `/addrp` with an attached image file only. Verify successful continuation to modal/forum.
- [ ] **Validation - Single Input (Link)**: Test `/addrp` with a hosted URL only. Verify successful continuation.
- [ ] **Render Test**: Render legacy RPs (stored links) alongside new RPs (direct uploads) to ensure zero breaking changes across old database entries.