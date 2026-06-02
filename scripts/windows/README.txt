Hearthlight — Windows quick start
==================================

Before you run any .bat file:
  1. Install Docker Desktop (WSL2 enabled) and start it.
  2. Install Git for Windows.
  3. Clone this repo (ZIP alone is not enough — submodules are required):

       git clone https://github.com/lauretta-io/hearthlight.git
       cd hearthlight
       git submodule update --init --recursive

Then double-click ONE of these (from this folder):

  1-control-plane.bat   — Dashboard + API only (fastest check)
  2-full-video-cpu.bat  — Full video test on CPU (upload a clip in the UI)

After 2-full-video-cpu.bat finishes:
  - Open http://localhost:3000
  - Settings → Sources → upload a short MP4 → Save
  - Monitor Run → Start

More help: Hearthlight_Windows_Setup_Guide.docx (repo root) or docs/containers.md
