include <tasklot_parameters.scad>

// TaskLot first-pass parametric enclosure.
// Coordinate system: X left-to-right, Y front-to-back, Z bottom-to-top.

module rounded_rect_2d(size, radius) {
    offset(r = radius) offset(delta = -radius) square(size);
}

module rounded_box(size, radius) {
    linear_extrude(height = size[2]) rounded_rect_2d([size[0], size[1]], radius);
}

module shell() {
    difference() {
        union() {
            // Open-bottom underbody plus printable top deck.
            difference() {
                rounded_box([base_width, base_depth, underbody_height + deck_thickness], corner_radius);
                translate([wall_thickness, wall_thickness, 0])
                    rounded_box([base_width - 2 * wall_thickness,
                                 base_depth - 2 * wall_thickness,
                                 underbody_height],
                                max(1, corner_radius - wall_thickness));
            }
            screw_bosses();
            reader_rails_all();
            // electronics_bumpers() lives on bottom_panel(), not here. The boards rest on the
            // panel, and unioning the bumpers into this hollow shell left them floating in the
            // void with nothing under them -- 7 loose islands in the exported mesh.
            restaurant_attachment_pad();
        }
        parking_markings();
        lcd_mount_slots();
        lcd_deck_cable_hole();
        bottom_screw_holes();
        front_io_openings();
    }
}

module reader_holder(center, deck_underside_z = underbody_height) {
    pocket_x = reader_pocket[1];
    pocket_y = reader_pocket[0];
    x0 = center[0] - pocket_x / 2;
    y0 = center[1] - pocket_y / 2;
    lip_z = deck_underside_z - reader_slot_height - reader_lip_thickness;
    wall_height = reader_holder_drop + 0.4;

    // Exact three-sided slide-in U-channel used by both the base and the test coupon.
    // The -X end is open. The PCB slides toward the +X backstop.

    // Two vertical guide walls, OUTSIDE the pocket so the clear channel equals the pocket.
    translate([x0, y0 - reader_rail_width, lip_z])
        cube([pocket_x + reader_rail_width, reader_rail_width, wall_height]);
    translate([x0, y0 + pocket_y, lip_z])
        cube([pocket_x + reader_rail_width, reader_rail_width, wall_height]);

    // Closed +X backstop, also outside the pocket.
    translate([x0 + pocket_x, y0 - reader_rail_width, lip_z])
        cube([reader_rail_width, pocket_y + 2 * reader_rail_width, wall_height]);

    // Inward-facing lower lips support the PCB while leaving its center and wires exposed.
    translate([x0, y0, lip_z])
        cube([pocket_x, reader_lip_width, reader_lip_thickness]);
    translate([x0, y0 + pocket_y - reader_lip_width, lip_z])
        cube([pocket_x, reader_lip_width, reader_lip_thickness]);
}

module reader_rails_all() {
    for (center = parking_reader_centers) reader_holder(center);
    reader_holder(record_reader_center);
    reader_holder(drive_reader_center);
}

module parking_markings() {
    // Four right-side spaces, engraved for paint fill.
    for (center = parking_reader_centers) {
        translate([center[0] - parking_space_length / 2,
                   center[1] - parking_space_width / 2,
                   underbody_height + deck_thickness - parking_line_depth]) {
            cube([parking_space_length, parking_line_width, parking_line_depth + 0.2]);
            translate([0, parking_space_width - parking_line_width, 0])
                cube([parking_space_length, parking_line_width, parking_line_depth + 0.2]);
            translate([parking_space_length - parking_line_width, 0, 0])
                cube([parking_line_width, parking_space_width, parking_line_depth + 0.2]);
        }
    }

    // Waiting-lane boundary lines across the front.
    for (y = [18, 55])
        translate([22, y, underbody_height + deck_thickness - parking_line_depth])
            cube([205, parking_line_width, parking_line_depth + 0.2]);
}

module electronics_bumpers() {
    // Low corner bumpers: positioning hints, not fitted slots.
    bumper_corners(mega_keepout_origin, mega_keepout);
    bumper_corners(power_bank_keepout_origin, power_bank_keepout);
}

module bumper_corners(origin, keepout) {
    s = 8;
    h = electronics_bumper_height;
    z = bottom_panel_thickness;   // boards sit on the bottom panel, not up under the deck
    for (dx = [0, keepout[0] - s], dy = [0, keepout[1] - s])
        translate([origin[0] + dx, origin[1] + dy, z]) cube([s, s, h]);
}

module restaurant_attachment_pad() {
    // Off by default: the building glues straight to the flat deck.
    // The raised pad also stood proud of the deck, which stopped the base printing deck-down.
    if (restaurant_pad_enabled)
    translate([restaurant_pad_origin[0], restaurant_pad_origin[1], underbody_height + deck_thickness - 1.4])
        difference() {
            rounded_box([restaurant_pad[0], restaurant_pad[1], 1.4], 3);
            for (pin_x = restaurant_pin_x)
                translate([restaurant_pad[0]/2 + pin_x, restaurant_pad[1] / 2, -3.1])
                    cylinder(h = 4.6, d = restaurant_pin_diameter);
        }
}

// Single source of truth for where the LCD frame sits and where its tabs land.
// Both the frame and the deck slots derive from these, so they cannot drift apart again.
function lcd_frame_origin_y() = base_depth - 8 - lcd_rear_depth;
function lcd_tab_local_y()    = lcd_rear_depth/2 - lcd_tab_size[1]/2;
function lcd_tab_global_y()   = lcd_frame_origin_y() + lcd_tab_local_y();

module lcd_mount_slots() {
    x_center = base_width / 2;
    c = lcd_tab_clearance;
    // Slot = tab + clearance, centred on the tab. Previously this used a separate hand-written
    // expression that sat 13 mm from the tabs, and was cut at exactly lcd_tab_size (0.00 clearance).
    for (x = lcd_tab_x)
        translate([x_center + x - c/2, lcd_tab_global_y() - c/2,
                   underbody_height + deck_thickness - 3])
            cube([lcd_tab_size[0] + c, lcd_tab_size[1] + c, 4]);
}

module lcd_deck_cable_hole() {
    // Through-deck path directly below the frame's upper-left rear wiring chase.
    frame_width = lcd_face[0] + 2 * (lcd_frame_wall + lcd_edge_clearance);
    x = base_width/2 - frame_width/2 + 5;
    y = base_depth - 39;
    translate([x, y, underbody_height - 0.1])
        rounded_box([lcd_cable_hole[0], lcd_cable_hole[1], deck_thickness + 0.2], 2);
}

module screw_bosses() {
    for (p = [[12,12], [base_width-12,12], [12,base_depth-12], [base_width-12,base_depth-12]])
        translate([p[0], p[1], 0])
            difference() {
                cylinder(h = underbody_height + 0.4, d = screw_boss_diameter);
                translate([0, 0, -0.1])
                    cylinder(h = underbody_height + 0.6, d = boss_tap_diameter);
            }
}

module bottom_screw_holes() {
    // Stop short of the boss so boss_tap_diameter survives. Previously this ran the full
    // underbody height at 3.4, reaming out the 2.6 pilot and leaving nothing to thread into.
    for (p = [[12,12], [base_width-12,12], [12,base_depth-12], [base_width-12,base_depth-12]])
        translate([p[0], p[1], -0.1]) cylinder(h = 0.2, d = screw_hole_diameter);
}

module front_io_openings() {
    // Through-holes in the front wall (Y=0). Positions are intentionally easy to adjust.
    for (item = [[front_led_x, record_led_opening_diameter],
                 [front_mic_x, microphone_opening_diameter],
                 [front_speaker_x, speaker_opening_diameter]])
        translate([item[0], -0.1, front_io_height])
            rotate([-90, 0, 0]) cylinder(h = wall_thickness + 0.3, d = item[1]);
}

module lcd_frame() {
    frame_width = lcd_face[0] + 2 * (lcd_frame_wall + lcd_edge_clearance);
    frame_depth = lcd_rear_depth;
    difference() {
        union() {
            // Perpendicular bezel/body.
            translate([-frame_width/2, 0, 0])
                rounded_box([frame_width, frame_depth, lcd_frame_height], 3);
            // Tabs are optional. The laser-cut deck uses a flat glue joint instead of slots.
            if (lcd_tab_print)
                for (x = lcd_tab_x)
                    translate([x, lcd_tab_local_y(), -3])
                        cube(lcd_tab_size);
        }
        // Visible window through the front.
        translate([-lcd_opening[0]/2, -0.1,
                   (lcd_frame_height - lcd_opening[1]) / 2])
            cube([lcd_opening[0], lcd_frame_wall + 0.3, lcd_opening[1]]);
        // Broad rear cavity, leaving a front bezel and edge-retention ledge.
        translate([-lcd_face[0]/2 - lcd_edge_clearance,
                   lcd_frame_wall,
                   (lcd_frame_height - lcd_face[1]) / 2])
            cube([lcd_face[0] + 2*lcd_edge_clearance,
                  frame_depth,
                  lcd_face[1]]);
        // Oversized upper-left-to-base wiring chase.
        translate([-lcd_face[0]/2,
                   lcd_frame_wall,
                   -0.1])
            cube([lcd_wire_chase[0], frame_depth + 0.2,
                  lcd_frame_height * 0.72]);
    }
}

module bottom_panel() {
    union() {
        difference() {
            translate([bottom_inset, bottom_inset, 0])
                rounded_box([base_width - 2*bottom_inset,
                             base_depth - 2*bottom_inset,
                             bottom_panel_thickness],
                            max(1, corner_radius - bottom_inset));
            for (p = [[12,12], [base_width-12,12], [12,base_depth-12], [base_width-12,base_depth-12]])
                translate([p[0], p[1], -0.1]) cylinder(h = bottom_panel_thickness + 0.2, d = screw_hole_diameter);
        }
        // Board-locating bumpers rise from the panel's top face, which is what the boards sit on.
        // Outside the difference() so the screw holes cannot bore through them.
        electronics_bumpers();
    }
}

module reader_coupon() {
    // Mechanically identical holder section: deck above, U-channel below, -X end open.
    coupon_size = [reader_pocket[1] + 2 * reader_rail_width + 12, reader_pocket[0] + 2 * reader_rail_width + 12];
    coupon_deck_underside = reader_holder_drop;
    translate([0, 0, coupon_deck_underside])
        rounded_box([coupon_size[0], coupon_size[1], deck_thickness], 2);
    reader_holder([coupon_size[0]/2, coupon_size[1]/2], coupon_deck_underside);
}

// Roof printed as its own part: prints flat-side-down, no interior support,
// and leaves the building walls open-topped so nothing has to bridge.
module restaurant_roof_part() {
    bw = restaurant_body[0]; bd = restaurant_body[1];
    difference() {
    union() {
        restaurant_roof(bw + 8, bd + 8, restaurant_roof_height);
        // Locating rim: drops inside the wall opening, 0.4mm clearance per side.
        translate([0, 0, -restaurant_rim_height])
            linear_extrude(height = restaurant_rim_height + 0.1)
                difference() {
                    square([bw - 2*restaurant_wall - 0.8, bd - 2*restaurant_wall - 0.8], center=true);
                    square([bw - 4*restaurant_wall - 0.8, bd - 4*restaurant_wall - 0.8], center=true);
                }
    }
    // Optional sign slot. One slot rather than matched sockets, so a redesigned sign
    // can drop in a single tab or two posts without the roof being re-cut.
    if (roof_sign_slot_enable)
        translate([-roof_sign_slot[0]/2,
                   roof_sign_slot_y - roof_sign_slot[1]/2,
                   roof_sign_slot_floor])
            cube([roof_sign_slot[0], roof_sign_slot[1], restaurant_roof_height + 5]);
    // Clearance for the corner tower, which passes straight through the roof plane.
    // Without this the separate roof collides with the tower and cannot seat at all.
    translate([-bw/2 + restaurant_tower[0]/2 + 5,
               -bd/2 + restaurant_tower[1]/2 + 5,
               -restaurant_rim_height - 1])
        translate([-restaurant_tower[0]/2 - roof_tower_clearance,
                   -restaurant_tower[1]/2 - roof_tower_clearance,
                   0])
            cube([restaurant_tower[0] + 2*roof_tower_clearance,
                  restaurant_tower[1] + 2*roof_tower_clearance,
                  restaurant_roof_height + restaurant_rim_height + 2]);
    }
}

module restaurant_roof(width, depth, height) {
    // Low hipped roof formed as a printable convex hull.
    hull() {
        translate([-width/2, -depth/2, 0]) cube([width, depth, 1]);
        translate([-width*0.36, -depth*0.30, height-1])
            cube([width*0.72, depth*0.60, 1]);
    }
}

module arrow_sign_2d() {
    polygon(points=[[-28,-5], [8,-5], [8,-11], [29,0], [8,11], [8,5], [-28,5]]);
}

// Arrow sign plus the two posts that carry it. Used in place on the fused restaurant,
// and available on its own (part="restaurant_sign") to print flat and glue on after a split.
module sign_and_posts(bd, bh) {
    for (x = [-18, 18])
        translate([x, -bd/2 + 8, bh + restaurant_roof_height - 2])
            cube(restaurant_sign_post, center=true);
    translate([0, -bd/2 + 8,
               bh + restaurant_roof_height + 18 - restaurant_sign_drop])
        rotate([90,0,0]) linear_extrude(height=restaurant_sign[1], center=true)
            arrow_sign_2d();
    // Raised label on the arrow; printable as one material and paintable later.
    if (restaurant_sign_text != "")
    translate([-10, -bd/2 + 5.8,
               bh + restaurant_roof_height + 18 - restaurant_sign_drop])
        rotate([90,0,0]) linear_extrude(height=0.9)
            text(restaurant_sign_text, size=restaurant_sign_text_size,
                 halign="center", valign="center", font="Arial:style=Bold");
}

// The sign laid flat on the bed: arrow face down, posts alongside. Glues onto the roof.
module restaurant_sign_part() {
    linear_extrude(height=restaurant_sign[1]) arrow_sign_2d();
    if (restaurant_sign_text != "")
        translate([-10, 0, restaurant_sign[1]])
            linear_extrude(height=0.9)
                text(restaurant_sign_text, size=restaurant_sign_text_size,
                     halign="center", valign="center", font="Arial:style=Bold");
    // Posts laid flat alongside, clear of the arrow (which spans y -11..+11).
    for (x = [-18, 18])
        translate([x, -14 - restaurant_sign_post[2], 0])
            cube([restaurant_sign_post[0], restaurant_sign_post[2], restaurant_sign_post[1]]);
}

module tasklot_restaurant(with_roof = restaurant_roof_attached) {
    bw = restaurant_body[0];
    bd = restaurant_body[1];
    bh = restaurant_body[2];
    opening_x = bw/2 - restaurant_drive_opening[0]/2 - 7;

    difference() {
        union() {
            // Hollow building shell.
            difference() {
                translate([-bw/2, -bd/2, 0])
                    rounded_box([bw, bd, bh], 3);
                translate([-bw/2 + restaurant_wall,
                           -bd/2 + restaurant_wall,
                           restaurant_wall])
                    cube([bw - 2*restaurant_wall,
                          bd - 2*restaurant_wall,
                          bh]);
            }

            if (with_roof)
                translate([0, 0, bh-0.2])
                    restaurant_roof(bw + 8, bd + 8, restaurant_roof_height);

            // Tall corner tower gives the familiar roadside silhouette.
            translate([-bw/2 + restaurant_tower[0]/2 + 5,
                       -bd/2 + restaurant_tower[1]/2 + 5,
                       0])
                difference() {
                    translate([-restaurant_tower[0]/2,
                               -restaurant_tower[1]/2,
                               0])
                        rounded_box(restaurant_tower, 2);
                    translate([-restaurant_tower[0]/2 + restaurant_wall,
                               -restaurant_tower[1]/2 + restaurant_wall,
                               restaurant_wall])
                        cube([restaurant_tower[0]-2*restaurant_wall,
                              restaurant_tower[1]-2*restaurant_wall,
                              restaurant_tower[2]]);
                }

            // Awning over the front service windows.
            translate([-20, -bd/2 + 0.5, 28])
                rotate([90,0,0]) linear_extrude(height=5)
                    polygon(points=[[-28,0], [28,0], [24,8], [-24,8]]);

            // Roadside arrow and its two posts ride on the roof, so they only exist when the
            // roof does. Previously only the POSTS were gated -- splitting the roof off left the
            // sign as a disconnected island floating 21 mm above the open walls.
            if (with_roof) sign_and_posts(bd, bh);

            // Two alignment pins fit the base attachment pad.
            if (restaurant_pin_print)
                for (pin_x = restaurant_pin_x)
                    translate([pin_x, 0, -3])
                        cylinder(h=3.5, d=restaurant_pin_diameter-0.3);
        }

        // Drive-through tunnel crosses the building front-to-back.
        translate([opening_x - restaurant_drive_opening[0]/2,
                   -bd/2 - 1,
                   -0.1])
            cube(restaurant_drive_opening);

        // Front windows and door as shallow recesses for paint/paper inserts.
        for (x = [-30, 0])
            translate([x - restaurant_window[0]/2,
                       -bd/2 - 0.1,
                       17])
                cube(restaurant_window);
        translate([-restaurant_door[0]/2,
                   -bd/2 - 0.1,
                   0])
            cube(restaurant_door);
    }
}

module assembly() {
    color("#303030") shell();
    translate([base_width/2, base_depth - 8 - lcd_rear_depth, underbody_height + deck_thickness])
        color("#4444aa") lcd_frame();
    translate([restaurant_pad_origin[0] + restaurant_pad[0]/2,
               restaurant_pad_origin[1] + restaurant_pad[1]/2,
               underbody_height + deck_thickness
                 + (restaurant_pad_enabled ? 1.2 : 0)])
        color("#eeeeee") tasklot_restaurant(with_roof=true);
}


// --- Glue-on reader holder (laser-cut deck track, added 8/24) ---
// The same slide-in U-channel as reader_holder(), but standalone: no deck plate above it,
// because the plywood IS the deck. Built with lip_z = 0 so it prints lips-and-walls-down
// with ZERO overhang and 100% bed contact. The TOP faces of the rails are the glue joint,
// so rails are widened from reader_rail_width to holder_glue_rail_width.
// Orientation in use: open end faces -X, board slides in, antenna face UP toward the deck,
// header hangs down between the two lips.
module reader_holder_glue(rail_w = holder_glue_rail_width) {
    pocket_x = reader_pocket[1];
    pocket_y = reader_pocket[0];
    x0 = 0;
    y0 = rail_w;
    // No +0.4 here. In the printed base the walls overshoot 0.4 mm INTO the deck; standalone,
    // the wall top face IS the glue joint, so that overshoot would become 0.4 mm of extra slot.
    wall_height = reader_holder_drop;

    // Two vertical guide walls, OUTSIDE the pocket so the clear channel equals the pocket.
    translate([x0, y0 - rail_w, 0])
        cube([pocket_x + rail_w, rail_w, wall_height]);
    translate([x0, y0 + pocket_y, 0])
        cube([pocket_x + rail_w, rail_w, wall_height]);

    // Closed +X backstop, also outside the pocket.
    translate([x0 + pocket_x, y0 - rail_w, 0])
        cube([rail_w, pocket_y + 2 * rail_w, wall_height]);

    // Inward-facing lower lips support the PCB while leaving its center and wires exposed.
    translate([x0, y0, 0])
        cube([pocket_x, reader_lip_width, reader_lip_thickness]);
    translate([x0, y0 + pocket_y - reader_lip_width, 0])
        cube([pocket_x, reader_lip_width, reader_lip_thickness]);
}

// All six holders on one plate: 4 parking spaces + record + drive-through.
module reader_holders_6() {
    fx = reader_pocket[1] + holder_glue_rail_width;        // X extent of one holder
    fy = reader_pocket[0] + 2 * holder_glue_rail_width;    // Y extent of one holder
    g  = holder_glue_plate_gap;
    for (i = [0:5])
        translate([(i % 3) * (fx + g), floor(i / 3) * (fy + g), 0])
            reader_holder_glue();
}

if (part == "assembly") assembly();
else if (part == "base") shell();
else if (part == "lcd_frame") lcd_frame();
else if (part == "bottom_panel") bottom_panel();
else if (part == "reader_coupon") reader_coupon();
else if (part == "restaurant") tasklot_restaurant(with_roof=true);
else if (part == "restaurant_body") tasklot_restaurant(with_roof=false);
else if (part == "restaurant_roof") restaurant_roof_part();
else if (part == "restaurant_sign") restaurant_sign_part();
else if (part == "reader_holder_glue") reader_holder_glue();
else if (part == "reader_holders_6") reader_holders_6();
