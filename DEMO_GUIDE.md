# Client demo guide

A 30–40 minute walkthrough that shows every capability live. All equipment in the
demo is simulated. Line 3 and the MQTT sensors run on the **lab field simulator**,
a separate program that behaves like a real PLC and real transmitters. The platform
talks to it over real Modbus TCP and MQTT, exactly as it will talk to the customer's
machinery.

## Before the client arrives (5 minutes)

1. Check that the stack is running: open `http://<server>:8000/api/health`. Every field should say `ok` / `running` / `ready`.
2. Open three browser windows:
   * **A:** `http://<server>:8000`, signed in as `operator@demo.example.com`
   * **B:** `http://<server>:8000` in a private window, signed in as `engineer@demo.example.com`
   * **C:** the lab presenter panel at `http://<server>:8090`. Keep it on your own screen; it stands in for the physical plant.
3. In C, make sure the E-stop is **healthy**, no faults are latched, and both cables are plugged in (click *Reset E-stop* and *Clear faults*).
4. All demo passwords are `demo1234`. Change them under **Settings** if the client will get access.

## The story

| # | Show | Where | What to say |
|---|---|---|---|
| 1 | Plant at a glance | A → **Overview** | One configurable model of the plant: assets, devices and live KPIs. The *Live + simulated* pill and `SIM` tags show where data comes from. Simulated data is never passed off as real. |
| 2 | 3D digital twin | A → **Live monitoring** | Status beacons per machine. Conveyors, drives and the robot animate only while they report a fresh *running* state. Switch **2D / 3D**: same objects, no duplicates. Click **CV-301** for live values and trends. |
| 3 | Real protocols | B → **Devices** | CV-301, MTR-301, PMP-401 and CP-001 come over **Modbus TCP** from the line PLC. TT-101, TT-201, EM-001 and EM-002 come over **MQTT**. Open a device to show the point map, the command map and live diagnostics (samples, round-trip time). |
| 4 | Onboard a device | B → **Devices → Connect device** | Pick an asset, then the template *Line PLC pump (Modbus TCP)*, then test the connection, discover registers, map points and commands, and activate. No code. Cancel at the end, or keep it inactive. |
| 5 | Safe control | A → **Live monitoring → CV-301 → Start/Stop** | The dialog runs **every safety check live**: permission, parameters, device online, interlocks (fail closed), rate limit and confirmation. After *Send*, follow the lifecycle *Sent → Acknowledged → Completed · verified*. "Verified" means the PLC's own feedback confirmed it, not just that the message was delivered. |
| 6 | Physical E-stop wins | C → **E-STOP** | The PLC drops the run outputs **on its own**. In A, alarms appear immediately (bell, toast, beacons turn red) and CV-301 shows *E-stop*. Try **Start** in A: blocked by the interlock *CP-001 E-stop must be healthy*. The software never overrides physical safety. Then C → *Reset E-stop*. |
| 7 | Four-eyes approval | A → CV-301 → **Speed setpoint** 1.1 m/s | The operator can only *request* it. In B → **Commands**, the request appears under *Awaiting approval*. The engineer approves it, and the belt speed changes and is verified. Requesters can't approve their own commands. |
| 8 | Fault handling | C → **Jam conveyor CV-301** | The PLC latches a fault and the platform raises an *Equipment fault* alarm. Acknowledge it in A → **Alerts**. Then C → *Clear faults* and the alert clears itself after it has stayed normal for 10 s. |
| 9 | Process alarms | C → **Overheat TT-101** | The coolant temperature climbs through warning (70 °C) to alarm (80 °C). The alert escalates and re-requires acknowledgement. Show the trend with limit lines on TT-101. |
| 10 | Communication loss | C → **Pull TT-201 cable** | A *Communication lost* warning appears within about 6 s. The value then turns *stale* (grey, never a fake value) about 15 s after the last reading. Plug it back in and both recover. |
| 11 | Build the twin | B → **Twin editor** | Drag a machine from *New*, move/rotate it with snapping, undo/redo, save with a message, open *History* and restore an older version. |
| 12 | Dashboards | A → **Dashboards** | Live gauges, trends and KPIs. *Edit* to add a widget. |
| 13 | Automation (no-code) | B → **Automations** → *Coolant overheat: start coolant pump* → **Edit** | WHEN TT-101 > 80 °C for 5 s THEN start PMP-401 and notify. Then C → **Overheat TT-101**: within ~40 s the rule fires, PMP-401 starts *through the same safety checks as a person*, and the notification appears in C's **Maintenance system inbox** with a verified signature. Show **Runs & dry run**: a step-by-step log, and a dry run with a what-if value. |
| 14 | Analytics & report | A → **Analytics** | Utilization and downtime per machine, energy kWh, production, compare machines. **Reports → Open printable report**: a one-page daily report (print to PDF) or CSV. |
| 15 | Historical playback | A → **Live monitoring → Replay history: Last 1 h** | The 3D plant replays recorded history at 10–300×. It's clearly marked PLAYBACK / REPLAY and controls are disabled. Scrub the timeline back to the E-stop from step 6. **Back to live**. |
| 16 | Simulation drills | B → **Simulation** → *Line 1 motor overload* → **Run** | Fault injection on *simulated* devices only (field devices are refused). MTR-101 current and winding temperature go into alarm; alerts and notifications fire; the scenario ends and values recover. |
| 17 | Accountability | B → **Audit log**, **Commands**, **Settings → Notifications → Delivery log** | Every configuration change, command, approval, acknowledgement, automation run and notification, with who and when. |

## Questions clients usually ask

* **Can the software override our safety systems?** No. It is supervisory only. PLC logic, safety relays and hardwired E-stops stay in charge; step 6 shows the PLC refusing.
* **What if the network drops during a command?** The command ends as *Timed out · state unverified* and the UI says to check locally. After a platform restart, interrupted commands are marked *failed, state unknown*, never assumed done.
* **How do we connect our machines?** Through Modbus TCP or MQTT today, directly or through a gateway. OPC UA, Siemens S7, EtherNet/IP and BACnet plug into the same adapter interface (see DEVICE_INTEGRATION.md).
* **Where does it run?** On a server or industrial PC on site; no cloud is required. Browsers never talk to PLCs.

## Reset after the demo

* C → *Reset E-stop*, *Clear faults*, plug both cables back in.
* Acknowledge leftover alerts under **Alerts → Acknowledge all**.
* If a simulation scenario is still running: **Simulation → Stop & restore**.
