// TaskLot CAD parameters — millimeters
// AI-assisted working model. Verify every physical fit with a test print.

// Export selector: "assembly", "base", "lcd_frame", "bottom_panel", "reader_coupon", "restaurant"
part = "assembly";

// Main envelope — fits a stated >=14 x 12 inch bed (355.6 x 304.8 mm).
base_width = 330;
base_depth = 270;
deck_thickness = 4;
underbody_height = 38;
wall_thickness = 3;
corner_radius = 5;

// Toy cars and surface interaction.
car_width = 20;
car_length = 40;
parking_space_width = 42;
parking_space_length = 62;
parking_line_width = 1.2;
parking_line_depth = 0.8;

// RC522 — approximate physical board, intentionally forgiving pocket.
// ⚠️ 39 is the datasheet short edge; four vendors list 40. NOT yet confirmed with calipers.
// reader_clearance must stay wider than that 1 mm disagreement until a real board is measured.
reader_board = [39, 60, 1.6];   // bare PCB outline. 1.6 = standard FR4 nominal, NOT measured.
reader_clearance = 1.0;         // was 0.7 -- narrower than the 39-vs-40 spread between sources
// The slot must clear the SOLDERED HEADER on the underside, not just the laminate.
// v2 derived slot height from reader_board[2] alone, giving 2.4 mm against a ~2.5 mm header.
reader_header_underside = 2.5;  // solder tails + plastic below the PCB; measure yours
reader_pocket = [reader_board[0] + 2 * reader_clearance,
                 reader_board[1] + 2 * reader_clearance];
reader_rail_width = 2.5;
reader_lip_width = 4;
reader_lip_thickness = 1.5;
reader_vertical_clearance = 0.8;
reader_slot_height = reader_board[2] + reader_header_underside + reader_vertical_clearance;
reader_holder_drop = reader_slot_height + reader_lip_thickness;
reader_wire_rise = 12.7;

// Reader centers derived from the sketch: four ranked spaces + record + drive-through.
parking_reader_centers = [
    [286, 55],
    [286, 110],
    [286, 165],
    [286, 220]
];
record_reader_center = [80, 32];
drive_reader_center = [103, 150];  // under the drive-through tunnel (was 145 = 42mm past it, car never read inside)

// LCD2004A face and approximate frame.
lcd_face = [98, 60];
// Window sized to clear the FULL viewing area, not the active area.
// Raystar RC2004A (same 98.0 x 60.0 outline as ours): viewing area 77.0 x 25.2,
// active/dot-matrix area 70.4 x 20.8, mounting holes 93.0 x 55.0.
// 73 x 35 cleared the characters but left only 1.3mm/side against the 77mm glass --
// less margin than the module's own 0.6mm slop in the pocket. 79 x 37 clears the
// viewing area by 1.0mm/side and 5.9mm top/bottom, absorbing the vertical VA offset
// nobody has measured. Bezel lip is still 10.1mm/side and covers the mounting holes.
lcd_opening = [79, 37];
lcd_edge_clearance = 0.6;
lcd_frame_wall = 4;
lcd_rear_depth = 34;
lcd_frame_base_depth = 14;
lcd_frame_height = 70;
lcd_wire_chase = [30, 20];
lcd_cable_hole = [34, 18];
// Both 12 mm tabs sit on the right/non-wire side of the frame, local X start positions.
lcd_tab_x = [12, 34];
lcd_tab_size = [12, 5, 4];       // the TAB only. The deck slot is derived from this + lcd_tab_clearance.
lcd_tab_clearance = 0.4;         // total, split evenly per side. v2 shrank lcd_tab_size and thought that
                                 // added clearance -- but the same parameter cut the slot, so it stayed 0.00.
lcd_tab_print = false;            // glue-only laser deck: omit tabs so the printed frame sits flat

// Electronics keepouts: allowance only, not fitted mounts.
mega_keepout = [112, 68, 28]; // Elegoo board is 101.5 x 53.3 mm; adds connector/service room.
power_bank_keepout = [155, 78, 30]; // PLACEHOLDER: update when the actual bank is chosen.
audio_board_keepout = [70, 60, 22]; // PLACEHOLDER: exact JESSINIE board dimensions unavailable.
mega_keepout_origin = [120, 10];
power_bank_keepout_origin = [10, 182];
electronics_bumper_height = 4;

// Front-wall recording/playback interface from the side-view sketch.
speaker_body = [15, 10, 3.5];
speaker_opening_diameter = 12;
microphone_body_diameter = 6;
microphone_opening_diameter = 7;
record_led_opening_diameter = 6;
front_io_height = 20;
front_led_x = 130;
front_mic_x = 158;
front_speaker_x = 216;

// Existing restaurant model candidate at 0.62 scale: ~102.3 x 62 x 83.7 mm.
restaurant_scale = 0.62;
restaurant_pad = [112, 76];
restaurant_pad_origin = [18, 112];
restaurant_pin_diameter = 3.2;
// Explicit asymmetric X positions relative to building/pad center.
// The second pin moved from +45 to 0 so it sits on solid floor, outside the +X drive tunnel.
restaurant_pin_x = [-45, 0];
restaurant_pin_print = false;   // false = omit pins so the building's floor sits flat on the bed
restaurant_pad_enabled = false; // false = no raised pad or pin sockets; the building just glues to the flat deck

// Original TaskLot drive-through building (separate print; millimeters).
restaurant_body = [106, 70, 46];
restaurant_wall = 3;
restaurant_roof_height = 19;
// Default for the `restaurant` part. The `restaurant_body` / `restaurant_roof` parts now force
// their own value, so the split is reproducible from the file without a -D override.
restaurant_roof_attached = false;
roof_tower_clearance = 0.4;       // gap around the tower where it passes through the roof
restaurant_rim_height = 0;        // 0 = flat-bottomed roof that just rests on the walls and glues (best print). >0 adds a locating rim.
restaurant_tower = [30, 24, 67];
restaurant_drive_opening = [34, restaurant_body[1] + 2, 27];
// --- Optional sign socket in the roof (added 8/24) ---
// ONE slot, deliberately, not a pair of round sockets: a slot lets a future sign use
// either a single wide tab or two posts without the roof having to know which. Unused
// it reads as a small vent slot in the roof, so it costs nothing to leave in.
// Sized to clear the tower cutout, which reaches x = -17.6 at this y -- 28 mm centred
// leaves 3.6 mm of solid roof between the slot end and that hole.
// Accepts: one tab up to 28 x 6, or two 5 mm posts on centres up to 23 mm.
roof_sign_slot        = [28, 6];   // [length along X, width along Y]
roof_sign_slot_y      = -27;       // the fused sign's own post line
roof_sign_slot_floor  = 4;         // solid roof left under the slot (roof is ~14 mm thick here)
roof_sign_slot_enable = true;

restaurant_sign = [62, 5, 22];
restaurant_sign_post = [5, 5, 25];
restaurant_sign_drop = 5;
restaurant_sign_text = "IN-N-OUT";  // "" to omit and just paint the arrow
restaurant_sign_text_size = 6;
restaurant_window = [25, 1.4, 14];  // 1.4 deep in a 3.0 wall leaves 1.60mm (was 2 -> 1.10mm, under 3 perimeters)
restaurant_door = [18, 1.4, 27];    // same: keeps 1.60mm of wall

// Bottom panel and fasteners.
bottom_panel_thickness = 3;
bottom_inset = 2;
screw_hole_diameter = 3.4;      // clearance hole in the bottom panel (M3 free fit)
boss_tap_diameter = 2.6;        // pilot in the boss so an M3 self-tapper actually grips
screw_boss_diameter = 9;

$fn = 48;

// --- Glue-on reader holders (laser-cut deck track, added 8/24) ---
// Standalone U-channels printed lips-down and glued to the underside of a laser-cut
// plywood deck. Same channel geometry as reader_holder(); only the rail width changes,
// because the top face of the rails IS the glue joint and 2.5 mm is a thin bond line.
holder_glue_rail_width = 5;     // vs reader_rail_width = 2.5 in the printed base
holder_glue_plate_gap  = 6;     // spacing between holders on the 6-up plate
