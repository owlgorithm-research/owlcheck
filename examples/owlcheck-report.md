# OwlCheck - Lantern Woods

**Godot**

Generated on 2026-11-04 15:44 with OwlCheck 0.11.0. Analysis done locally.

| Critical | Warning | Recommended | OK |
|---|---|---|---|
| 3 | 11 | 6 | 1 |

## Critical

- [ ] **Demo preset 'Steam Demo' exports the whole game** _(Demo)_  
  The preset exports every resource (7 scenes). Locking levels in code doesn't remove them from the .pck: anyone can extract the full game from the demo file.  
  **How to fix:** Change the preset filter to 'Export selected scenes' and tick only what the demo uses, or fill the exclude filter with the full game's folders.
  - `scenes/boss_final.tscn`
  - `scenes/level_01.tscn`
  - `scenes/level_02.tscn`
  - `scenes/level_03.tscn`
  - `scenes/level_04.tscn`
  - `scenes/level_05.tscn`

- [ ] **Credential files going into the build** _(Files)_  
  .env files, keys or keystores are included in the export.  
  **How to fix:** Remove them from the preset's include filter and move these files out of the project folder.
  - `.env`

- [ ] **Possible keys or passwords inside the build** _(Secrets)_  
  These files go into the exported game. Anyone who extracts the pack can read the values.  
  **How to fix:** Take the keys out of the project. If the game needs to talk to a service, put your own server in between. Rotate (revoke) any key that already shipped in a build.
  - `scripts/leaderboard.gd:2 - 'API_KEY' = a8F3********`
  - `scripts/leaderboard.gd:3 - Discord webhook: http********`

## Warning

- [ ] **Leftover breakpoints in the code** _(Debug)_  
  'breakpoint' does nothing in the final build, but it points to test code left behind.  
  **How to fix:** Remove them before shipping.
  - `scripts/main.gd:8`

- [ ] **Possible cheats or developer menus** _(Debug)_  
  Terms typical of test tools show up in the exported code. Players tend to find and trigger these shortcuts.  
  **How to fix:** Guard them with 'if OS.is_debug_build():' or a feature tag that only exists in the test build.
  - `scripts/main.gd:7 - 'god_mode'`

- [ ] **Unguarded command-line hooks** _(Debug)_  
  The game reads command-line arguments (e.g. --autotest) with no debug-build check around them. Any player can pass the argument and trigger the test mode.  
  **How to fix:** Wrap them in 'if OS.is_debug_build():' or use OS.has_feature() with a test-only tag.
  - `scripts/main.gd:3`

- [ ] **Demo lock done only in code** _(Demo)_  
  has_feature('demo') hides content during play, but the content is still in the pack.  
  **How to fix:** Combine the code lock with the export filter; never rely on it alone.
  - `scripts/main.gd`

- [ ] **Preset 'Windows Desktop': work files in the build** _(Files)_  
  Documents, drafts or art source files are being exported. A leaked GDD or note gives away plans and upcoming content.  
  **How to fix:** Adjust the include filter or add those folders to the exclude filter. Work-only folders can get a .gdignore file.
  - `docs/GDD.md`

- [ ] **Fonts without a license file next to them** _(Licenses)_  
  Many free fonts (e.g. OFL-licensed ones) require shipping the license alongside them. Commercial fonts may not even allow use in games.  
  **How to fix:** Put each font's license file in the same folder and mention it in the credits.
  - `fonts/Pixel.ttf`

- [ ] **Default Godot icon** _(Metadata)_  
  The project icon is still the little blue robot every new project starts with.  
  **How to fix:** Replace it with your game's icon.

- [ ] **Preset 'Steam Demo': default identifier (com.example.lanternwoods)** _(Metadata)_  
  Stores use this identifier as the app's unique ID, and it can't be changed later.  
  **How to fix:** Use something like com.yourstudio.yourgame.

- [ ] **Preset 'Windows Desktop' (Windows Desktop): pack (.pck) not encrypted** _(Protection)_  
  Any public extraction tool can open the .pck and copy scenes, scripts and assets.  
  **How to fix:** Turn on 'Encrypt PCK' and 'Encrypt Directory'. This requires compiling your own export templates with the key (SCRIPT_AES256_ENCRYPTION_KEY). Someone who knows how can extract the key from the executable, so treat it as a barrier, not a vault.

- [ ] **Preset 'Windows Desktop' (Windows Desktop): scripts exported as text** _(Protection)_  
  Your GDScript code ships readable inside the build, names and comments included.  
  **How to fix:** In the preset's Scripts tab, switch to 'Compressed binary tokens'.

- [ ] **Preset 'Steam Demo' (macOS): pack (.pck) not encrypted** _(Protection)_  
  Any public extraction tool can open the .pck and copy scenes, scripts and assets.  
  **How to fix:** Turn on 'Encrypt PCK' and 'Encrypt Directory'. This requires compiling your own export templates with the key (SCRIPT_AES256_ENCRYPTION_KEY). Someone who knows how can extract the key from the executable, so treat it as a barrier, not a vault.

## Recommended

- [ ] **No record of AI usage in the project** _(AI)_  
  Steam asks you to disclose AI-generated content when registering the game. Keeping a record in the project (what was generated, with which tool, what was edited by hand) makes the disclosure easier and documents it if anyone asks.  
  **How to fix:** Create an AI_DISCLOSURE.md at the project root, even if it's just to say you didn't use AI.

- [ ] **Print calls in exported code (2)** _(Debug)_  
  Prints go to the player's log and can reveal internal structure or hint at ways to cheat.  
  **How to fix:** Remove the debugging ones or switch to print_debug (which only shows in debug builds).
  - `scripts/main.gd: 2`

- [ ] **TODO/FIXME/HACK markers (1)** _(Debug)_  
  They don't affect the game, but check whether any of them is unfinished work before release.  

- [ ] **No credits or license file at the root** _(Licenses)_  
  Godot's MIT license requires including the engine's copyright notice in the game (credits screen or a file). The same goes for third-party fonts, plugins and music.  
  **How to fix:** Create a CREDITS.md and a credits screen with Godot's notice and one for each third-party asset.

- [ ] **Project has no version number** _(Metadata)_  
  A version helps players report bugs and helps you track builds.  
  **How to fix:** Set application/config/version (e.g. 0.1.0-demo).

- [ ] **Preset 'Windows Desktop': executable details left blank** _(Metadata)_  
  They show up under Properties > Details for the .exe on Windows. Leaving them blank looks amateurish and can increase antivirus warnings.  
  **How to fix:** Fill them in on the preset's Options tab.
  - `company_name`
  - `product_name`
  - `file_version`
  - `product_version`

## OK

- [x] **Preset 'Steam Demo' (macOS): scripts exported as binary** _(Protection)_  
  Helps against casual reading. Decompilers can still rebuild the code.  
