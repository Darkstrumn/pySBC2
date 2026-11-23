# SBC controller appliance backlog

Plan an in-place boot-to-app installation on the existing Pi first, then carry it forward to the next Raspberry Pi OS rebuild. Keep the current Buster image bootable as the hardware reference and rollback. The production Pi is the dedicated SBC controller CPU and MFD. Its normal interface should open automatically, like the Strike 7 control panel, with a maintenance mode available when needed.

## RC1 baseline

Use the manually launched Python runtime in `sbc-driver-test1.py` as the RC1 candidate. Qualify its polling responsiveness on the physical controller before making it the default. The console already supports keyboard navigation between the main and settings views. Touch handling exists in `touch_input.py`, but switching views by touch has yet to work on the device. Pygame provides an existing graphical path. The Nostromo v1 and GameVoice puck have been probed through evdev and still need production mappings.

## 1. Install, update, and boot the controller runtime

- Continue development and testing with `sbc-driver-test1.py`. The final application name is `firmware_dark_sbc.py`. Decide at release whether to promote the entry point in the repository or install it under the final name, keeping one maintained implementation.
- Add an update script that uses the merged `main` branch, fast-forwards safely, checks for conflicting tracked edits and preserves local profiles and calibration. For the in-place rollout, use the current powerdown chord to quit the running app before updating. Treat that exit as the maintenance window until a dedicated maintenance flow is installed.
- Support the current Pi's local framebuffer launch for the in-place installer. Verify boot-to-app and maintenance exit on the existing image before carrying the setup to a newer Raspberry Pi OS.

- Extend `scripts/install_rpi.sh` to install the runtime, dependencies, device permissions, and service and display-session configuration on the selected Raspberry Pi OS image. Start by reproducing the working manual launch and recording its interpreter, user, working directory, and display environment.
- Run the controller under supervision and bring up the MFD in the correct display session without manual login. Present a startup or fault status on the MFD if the controller is absent or the runtime cannot start.
- Make installation repeatable. Preserve device profiles and local configuration across reinstall, and document how to disable appliance startup during recovery.
- Acceptance test — a clean install on a spare SD card cold-boots into the controller UI with no keyboard attached. The SBC startup sequence, input, and LED output work on the physical device. Repeating the install preserves local configuration.

## 2. Restart and enter maintenance mode

- Restart after deliberate **application** exit and recoverable faults. Give orderly exit time to release input devices and finish shutdown effects. Keep deliberate Pi power-off and reboot distinct from a runtime restart.
- Provide a brief, visible restart window. A designated held controller chord during that window requests diagnostics and suppresses the pending restart. Provide an equivalent keyboard sequence for maintenance and a boot-time entry path. Choose the chords after checking existing control assignments and startup/shutdown combinations.
- Keep gesture detection available if the runtime has already exited. Give the supervisor or a separate input monitor responsibility for the restart window, with explicit handoff for any device requiring exclusive access. Provide a fallback maintenance entry if the SBC is absent.
- Count consecutive failed attempts to enter controller mode. At a configurable threshold, pause automatic relaunches and show the failure on the MFD with **Reboot** and **Power Down** choices. If a later boot reaches the threshold again, show the prompt again. Clear the count on every Pi reboot and once the controller runtime successfully reaches its operational state. Starting a process alone does not count as successful re-entry.
- Maintenance remains an operator-selected mode. Keep the maintenance gesture available during each restart window and allow the operator to select maintenance from the recovery screen. Diagnostics should expose runtime and device status, recent logs, and an explicit way back to controller mode.
- Acceptance test — verify normal exit and isolated faults relaunch, consecutive failed entries reach the on-screen prompt, and either successful re-entry or reboot clears the count. Verify a persistent fault reaches the prompt again after reboot, power-down halts relaunches, and the operator can toggle into maintenance and back to a single controller runtime.

## 3. Deliver keyboard-free MFD and auxiliary controls

- Bring up the official Raspberry Pi 7-inch touchscreen end to end. Identify its input device consistently, check permissions and coordinate mapping, and make taps switch between the main and settings views. Validate after reboot and at the installed display orientation.
- Use the graphical MFD for settings and diagnostics. Start with touch tabs, large controls, and touch-friendly fields. Add an on-screen keyboard for fields that require text and configuration for additional touch controls.
- Map the Nostromo v1 and GameVoice puck as auxiliary surfaces for a limited set of navigation and action commands. Keep their mappings configurable and handle reconnects without repeated or stuck actions.
- Acceptance test — with the physical keyboard unplugged, navigate main and settings, change and save a setting, enter text where needed, and use both auxiliary devices after cold boot and reconnect.

## 4. Run and expose local Node-RED

- Install and enable Node-RED as a boot service with persistent flows and settings. Validate the repository flows selected for RC1 against the Pi's local controller event and command routes.
- Add an MFD action to open the local editor from maintenance mode and return to the controller interface. Verify the touchscreen and on-screen keyboard are usable there for the intended editing tasks.
- Keep the production port and access policy open until deployment. Retain the existing port for initial bring-up. Decide whether LAN editing is needed before exposing the editor beyond the Pi and configure authentication for that access.
- Acceptance test — Node-RED starts on reboot, selected flows exchange events with the controller, saved flows persist, and the operator can open and leave the local editor from the MFD.

## Release gate

Use the spare image to test cold boot, polling under normal load, touch and auxiliary input, intentional exit, fault recovery, maintenance entry, local Node-RED access, and return to controller mode. Keep a keyboard available for bench recovery until the keyboard-free checks pass. Here, controller “firmware” means the installed appliance software and its operating mode. The requested “bootloader” experience is the maintenance entry above.
