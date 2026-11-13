// TaskLot laser-cut conversion — dimensions in millimeters.
// AI-assisted working model. Measure the actual plywood and update material_thickness.

part = "sheet_1_cut";
material_thickness = 3.0;
kerf = 0.15;                  // recorded for the shop; test before cutting fitted hardware openings

deck = [330, 270];
wall_height = 38;
lcd_opening = [79, 37];
lcd_face = [106, 70];

reader_board = [41, 62];      // includes 1 mm/side clearance around nominal RC522
reader_outer = [49, 70];
reader_placed = [67, 51];     // exact footprint of each printed glue-on holder
reader_centers = [[286,55], [286,110], [286,165], [286,220], [80,36], [103,150]];

module rounded_rect(size, r=3) {
    offset(r=r) offset(delta=-r) square(size);
}

module deck_cut() {
    difference() {
        rounded_rect(deck, 5);
        // Directly beneath the printed rear LCD frame's upper-left wiring chase.
        translate([115, 231]) rounded_rect([34, 18], 2);
    }
}

module deck_score() {
    // Tiny corner marks force the score SVG to retain the same 330 x 270 canvas as the cut SVG.
    square([0.01,0.01]);
    translate([329.99,269.99]) square([0.01,0.01]);
    // Parking-space outlines and rank labels are engraving guides, not through-cuts.
    for (i = [0:3]) {
        y = 34 + i * 55;
        translate([255, y]) difference() {
            square([62, 42]);
            translate([1.2,1.2]) square([59.6,39.6]);
        }
        translate([260, y+5]) text(str(i+1), size=8, font="Arial:style=Bold");
    }
    // Waiting lane and drive-through placement guides.
    translate([18, 12]) difference() { square([120,42]); translate([1.2,1.2]) square([117.6,39.6]); }
    translate([28, 22]) text("WAIT / RECORD", size=6, font="Arial:style=Bold");
    translate([18,112]) difference() { square([112,76]); translate([1.2,1.2]) square([109.6,73.6]); }
    translate([38,119]) text("DRIVE-THROUGH", size=5, font="Arial:style=Bold");
    // Printed LCD frame footprint: 107.2 x 34 mm, centered at X=165 and glued flat.
    translate([111.4,228]) difference() {
        square([107.2,34]);
        translate([1.2,1.2]) square([104.8,31.6]);
    }
}

module deck_underside_score() {
    square([0.01,0.01]);
    translate([329.99,269.99]) square([0.01,0.01]);
    // Flip/mirror instruction is handled in README; these locate the six printed U-holders.
    for (c = reader_centers)
        translate([c[0]-reader_placed[0]/2, c[1]-reader_placed[1]/2])
            difference() { square(reader_placed); translate([1,1]) square([reader_placed[0]-2,reader_placed[1]-2]); }
}

module bottom_cut() {
    difference() {
        rounded_rect([326,266], 4);
        // Large service opening keeps batteries, USB, and wiring accessible.
        translate([18,18]) rounded_rect([220,105], 6);
        // Cable ties / straps for the provisional power bank.
        translate([25,185]) square([4,45]);
        translate([185,185]) square([4,45]);
    }
}

module front_wall() {
    difference() {
        square([330,wall_height]);
        translate([127,9]) circle(d=6);
        translate([154.5,8.5]) circle(d=7);
        translate([210,10]) circle(d=12);
        // Mega USB/power service opening.
        translate([250,5]) rounded_rect([62,24],3);
    }
}
module back_wall() {
    difference() {
        square([330,wall_height]);
        // Rounded power-cord pass-through; fully enclosed so the wall stays one piece.
        translate([155,10]) rounded_rect([20,14],3);
    }
}
module side_wall() { square([264,wall_height]); }

module reader_spacer_u() {
    difference() {
        square(reader_outer);
        // Open insertion end at +Y.
        translate([(reader_outer[0]-reader_board[0])/2,4]) square([reader_board[0],reader_outer[1]]);
    }
}
module reader_spacer_u_down() {
    // Same part rotated 180 degrees for interlocking nests.
    translate(reader_outer) rotate(180) reader_spacer_u();
}
module reader_lip_u() {
    difference() {
        square(reader_outer);
        // 4 mm inward lips support the PCB; +Y remains open for insertion/wires.
        translate([8,4]) square([reader_outer[0]-16,reader_outer[1]]);
    }
}

module lcd_bezel() {
    difference() {
        square(lcd_face);
        translate([(lcd_face[0]-lcd_opening[0])/2, 18]) rounded_rect(lcd_opening,2);
    }
}
module lcd_rear() {
    difference() {
        square(lcd_face);
        translate([7,8]) rounded_rect([92,52],3);
        // Oversized upper-left wire exit.
        translate([5,42]) square([34,24]);
    }
}
module lcd_brace() {
    polygon([[0,0],[65,0],[0,65]]);
}

// Recovery LCD becomes an open-bottom box rather than a flat frame with kickstand braces.
// With 1/8 in (3.175 mm) front and rear plates, a 27.65 mm connector depth preserves the
// printed frame's 34 mm total front-to-back envelope. The top fits between the two sides.
recovery_ply = 3.175;
lcd_box_inner_depth = 34 - 2*recovery_ply;       // 27.65 mm
module lcd_box_side() { square([lcd_box_inner_depth, lcd_face[1]]); }
module lcd_box_top()  { square([lcd_face[0] - 2*recovery_ply, lcd_box_inner_depth]); }

module restaurant_front() {
    difference() {
        union() {
            square([106,46]);
            translate([0,46]) polygon([[0,0],[53,19],[106,0]]);
        }
        // Drive-through opening on right side.
        translate([62,0]) rounded_rect([34,27],3);
        translate([10,13]) square([25,14]);
    }
}
module restaurant_back() {
    difference() {
        square([106,46]);
        translate([62,0]) rounded_rect([34,27],3);
    }
}
module restaurant_side() { square([70,46]); }
module restaurant_roof() {
    // Flat replacement for the failed printed roof: exact 114 x 78 mm outer footprint
    // with the same 30.8 x 24.8 mm corner-tower clearance as the 3D CAD roof.
    difference() {
        square([114,78]);
        translate([8.6,8.6]) square([30.8,24.8]);
    }
}
module restaurant_sign() {
    union() {
        polygon([[0,5],[49,5],[49,0],[62,11],[49,22],[49,17],[0,17]]);
        translate([8,-25]) square([5,30]);
        translate([45,-25]) square([5,30]);
    }
}
module restaurant_sign_score() {
    translate([4,7]) text("IN-N-OUT", size=6, font="Arial:style=Bold");
}


// ---------------------------------------------------------------------------
// ULS layer split (added 8/24, AI-assisted with Claude Code).
// The Universal VLS 3.60 separates operations by color: pure red = vector cut,
// pure blue = vector etch, black fill = raster engrave. OpenSCAD cannot emit
// colors, so geometry is split into single-operation parts here and recombined
// with stroke/fill by make_uls_files.py. The original sheet_* parts are
// untouched; these are additive.
// ---------------------------------------------------------------------------

// Frames only — vector etch (blue). Drawn as 1.2 mm closed bands, so the laser
// traces two parallel lines and the stall reads as a painted stripe, not a scratch.
module deck_score_lines() {
    for (i = [0:3]) {
        y = 34 + i * 55;
        translate([255, y]) difference() {
            square([62, 42]);
            translate([1.2,1.2]) square([59.6,39.6]);
        }
    }
    translate([18, 12]) difference() { square([120,42]); translate([1.2,1.2]) square([117.6,39.6]); }
    translate([18,112]) difference() { square([112,76]); translate([1.2,1.2]) square([109.6,73.6]); }
    translate([111.4,228]) difference() {
        square([107.2,34]);
        translate([1.2,1.2]) square([104.8,31.6]);
    }
}

// Text only — raster engrave (black fill). Vector-etching glyph outlines gives
// hollow, stencil-looking letters at these sizes; a raster pass burns them solid.
module deck_score_text() {
    for (i = [0:3]) {
        y = 34 + i * 55;
        translate([260, y+5]) text(str(i+1), size=8, font="Arial:style=Bold");
    }
    translate([28, 22]) text("WAIT / RECORD", size=6, font="Arial:style=Bold");
    translate([38,119]) text("DRIVE-THROUGH", size=5, font="Arial:style=Bold");
}


// Visible lot markings -> RASTER (solid black fill). Thin score lines were too faint to
// see on the first printed deck; a raster pass burns them as solid
// 1.2 mm dark bands rather than two thin scorch lines, which is what makes the
// board read as a parking lot from across the room.
module deck_raster() {
    for (i = [0:3]) {
        y = 34 + i * 55;
        translate([255, y]) difference() {
            square([62, 42]);
            translate([1.2,1.2]) square([59.6,39.6]);
        }
        translate([260, y+5]) text(str(i+1), size=8, font="Arial:style=Bold");
    }
    translate([18, 12]) difference() { square([120,42]); translate([1.2,1.2]) square([117.6,39.6]); }
    translate([28, 22]) text("WAIT / RECORD", size=6, font="Arial:style=Bold");
}

// Assembly guides that end up HIDDEN under glued-on printed parts (the
// restaurant covers the drive-through box, the LCD frame covers its footprint).
// Thin vector etch is right here -- a bold burn would show around the edges and
// would only add raster time for marks nobody sees.
module deck_etch() {
    translate([18,112]) difference() { square([112,76]); translate([1.2,1.2]) square([109.6,73.6]); }
    translate([38,119]) text("DRIVE-THROUGH", size=5, font="Arial:style=Bold");
    translate([111.4,228]) difference() {
        square([107.2,34]);
        translate([1.2,1.2]) square([104.8,31.6]);
    }
}


// ---------------------------------------------------------------------------
// In-N-Out style sign for the drive-through prop. Drawn here rather than traced
// from the company's artwork: this is an original rendition in the same visual
// idiom (the angled boomerang arrow plus wordmark) for a one-off class prop.
// Cut the outline, raster the lettering so it reads dark on pale birch.
// ---------------------------------------------------------------------------
sign_tilt = 17;

module innout_arrow_shape() {
    // Boomerang: tapered tail on the left, thick shaft, triangular head right.
    polygon([[0,-10],[38,-18],[168,-22],[168,-38],[232,0],[168,38],[168,22],[38,20],[0,26]]);
}
module innout_sign_cut() {
    rotate([0,0,sign_tilt]) union() {
        innout_arrow_shape();
        // Mounting tang under the tail, so it can slot into a base or be glued.
        translate([26,-40]) square([16,26]);
        translate([120,-44]) square([16,30]);
    }
}
module innout_sign_raster() {
    rotate([0,0,sign_tilt]) {
        translate([26,-9]) text("IN-N-OUT", size=25, font="Arial:style=Bold", spacing=1.02);
        translate([176,-9]) text("!", size=1, font="Arial:style=Bold");
    }
}
module innout_burger_cut()   { square([116,34]); }
module innout_burger_raster(){ translate([9,9]) text("BURGER", size=17, font="Arial:style=Bold", spacing=1.15); }

// Placed in the strip right of the deck on the deck sheet.
module deck_sheet_sign_cut() {
    translate([352,84])  innout_sign_cut();
    translate([368,18])  innout_burger_cut();
}
module deck_sheet_sign_raster() {
    translate([352,84])  innout_sign_raster();
    translate([368,18])  innout_burger_raster();
}

// Underside holder guides, pre-mirrored about the deck centerline (x = 165).
// The deck outline is a symmetric rounded rectangle, so after the cut the deck
// can be lifted, flipped left-to-right, and dropped back into its own hole in
// the parent sheet — which re-registers it for free. This part is what you run
// then, at the SAME bed position as the top-face run.
module deck_underside_score_mirrored() {
    translate([deck[0],0]) mirror([1,0,0]) deck_underside_score_geom();
}

module deck_underside_score_geom() {
    for (c = reader_centers)
        translate([c[0]-reader_placed[0]/2, c[1]-reader_placed[1]/2])
            difference() { square(reader_placed); translate([1,1]) square([reader_placed[0]-2,reader_placed[1]-2]); }
}

// Laid out for 12 x 24 in (304.8 x 609.6 mm) stock on the VLS 3.60.
//
// All six parts total 220,960 mm2 against a 185,806 mm2 sheet -- 119%, so one sheet
// was never possible. Two people, one sheet each.
//
// THE DECK SHEET carries the deck plus everything that fits in the strip beside it.
// The deck is 330 wide, leaving ~250 mm of clear width. The 264 mm side walls do not
// fit lying down, but they fit STOOD ON END (38 x 264) because the sheet is 304.8 deep.
// The 330 mm front/back walls fit neither way -- 330 exceeds the depth -- so they are
// the only walls left for the second (walls) sheet.
//
// Everything here is placed to clear 599.4 x 299.7 mm, i.e. a nominal "12 x 24" sheet
// that is really 11.8 x 23.6 in. Widest extent is 573 mm on the page.
module uls_deck_sheet_extras() {
    // Two side walls stood on end, in the strip beside the deck.
    translate([334,0]) square([38,264]);
    translate([378,0]) square([38,264]);
    // Corner blocks. README step 5 wants "square blocks or small angle brackets inside
    // the corners", and step 6 screws the bottom panel into them. Laminate five 25 mm
    // squares per corner for a ~15.9 mm post. 20 squares = 4 corners.
    for (r=[0:3]) for (c=[0:4])
        translate([422 + c*29, r*29]) square([25,25]);
    // Plywood LCD frame, as insurance. At the time nobody had confirmed the
    // printed LCD frame was actually run, and this costs ~1 min of laser time on wood
    // that is being burned anyway. If the print exists, throw these two away.
    translate([422,116]) lcd_bezel();
    translate([422,192]) lcd_rear();
}

// THE WALLS SHEET. Front and back walls only -- 330 x 82 mm, a scrap.
module uls_walls_sheet() {
    front_wall();
    translate([0,44]) back_wall();
}

module uls_bottom_cut() { bottom_cut(); }

// One-sheet recovery nest for parts that failed at the 3D printer:
// 18 RFID laminations, LCD box parts, restaurant roof, and sign.
// Fits within 572 x 216 mm before the standard 10 mm page margin.
module uls_recovery_parts_cut() {
    // RFID holders: two 3.175 mm spacer layers and one lower-lip layer per reader.
    // Rows 1-2 = 12 spacers; row 3 = 6 retaining lips.
    for (row=[0:1]) for (col=[0:5])
        translate([col*52,row*73]) reader_spacer_u();
    for (col=[0:5])
        translate([col*52,146]) reader_lip_u();

    // Printed-LCD replacement: open-bottom box, no tabs or external braces.
    translate([320,0]) lcd_bezel();
    translate([432,0]) lcd_rear();
    translate([440,76]) lcd_box_top();
    translate([440,110]) lcd_box_side();
    translate([472,110]) lcd_box_side();

    // Printed restaurant replacements. Roof includes the corner-tower cutout.
    translate([320,76]) restaurant_roof();
    translate([510,185]) restaurant_sign();
}

module uls_recovery_parts_etch() {
    translate([510,185]) restaurant_sign_score();
}

// 8/25 recut after the combined sheet's 281 mm front/back walls proved 49 mm
// short for the 330 mm deck. These restore both feature-bearing walls to their
// canonical 330 x 38 mm size and add the restaurant roof and sign.
module uls_final_recut_cut() {
    // Laptop handles all audio; this wall is intentionally solid.
    square([330,wall_height]);
    translate([0,41]) back_wall();
    translate([0,82]) restaurant_roof();
    // Sign geometry extends 25 mm below its local origin; Y=107 puts its
    // lowest edge at 82, preserving the 3 mm gap above the wall row.
    translate([117,107]) restaurant_sign();

    // Eight thin-rail RFID spacer U's, nested as four opposing pairs. In each
    // pair, one leg sits inside the neighboring U's opening without material
    // overlap. Four use otherwise-empty space beside the roof/sign.
    translate([182,82]) reader_spacer_u();
    translate([190,90]) reader_spacer_u_down();
    translate([242,82]) reader_spacer_u();
    translate([250,90]) reader_spacer_u_down();

    // Remaining four use one compact 70 mm row below the full walls.
    translate([0,163]) reader_spacer_u();
    translate([8,171]) reader_spacer_u_down();
    translate([60,163]) reader_spacer_u();
    translate([68,171]) reader_spacer_u_down();
}

module uls_final_recut_etch() {
    translate([117,107]) restaurant_sign_score();
}

// Sheet layouts stay below 600 x 300 mm. Rearrange in laser software if the shop bed differs.
module sheet_1_cut() { deck_cut(); }
module sheet_1_score() { deck_score(); }
module sheet_1_underside_score() { deck_underside_score(); }
module sheet_2_cut() {
    bottom_cut();
    translate([0,275]) front_wall();
    translate([0,318]) back_wall();
    translate([0,361]) side_wall();
    translate([0,404]) side_wall();
}
module sheet_3_cut() {
    lcd_bezel();
    translate([115,0]) lcd_rear();
    translate([230,0]) lcd_brace();
    translate([300,0]) lcd_brace();
    translate([0,85]) restaurant_front();
    translate([115,85]) restaurant_back();
    translate([230,85]) restaurant_side();
    translate([305,85]) restaurant_side();
    translate([0,155]) restaurant_roof();
    translate([125,180]) restaurant_sign();
}
module sheet_3_score() {
    // Registration marks preserve the cut sheet's full extents in OpenSCAD's cropped SVG export.
    square([0.01,0.01]);
    translate([374.99,230.99]) square([0.01,0.01]);
    translate([125,180]) restaurant_sign_score();
}
module sheet_4_reader_holders() {
    // 12 spacer U's (two per reader) plus 6 lip U's.
    for (row=[0:2]) for (col=[0:3]) translate([col*55,row*76]) reader_spacer_u();
    for (row=[0:1]) for (col=[0:2]) translate([230+col*55,row*76]) reader_lip_u();
}

if (part == "deck_sheet_sign_cut") deck_sheet_sign_cut();
else if (part == "deck_sheet_sign_raster") deck_sheet_sign_raster();
else if (part == "deck_raster") deck_raster();
else if (part == "deck_etch") deck_etch();
else if (part == "deck_score_lines") deck_score_lines();
else if (part == "deck_score_text") deck_score_text();
else if (part == "deck_underside_score_mirrored") deck_underside_score_mirrored();
else if (part == "uls_deck_sheet_extras") uls_deck_sheet_extras();
else if (part == "uls_walls_sheet") uls_walls_sheet();
else if (part == "uls_bottom_cut") uls_bottom_cut();
else if (part == "uls_recovery_parts_cut") uls_recovery_parts_cut();
else if (part == "uls_recovery_parts_etch") uls_recovery_parts_etch();
else if (part == "uls_final_recut_cut") uls_final_recut_cut();
else if (part == "uls_final_recut_etch") uls_final_recut_etch();
else if (part == "sheet_1_cut") sheet_1_cut();
else if (part == "sheet_1_score") sheet_1_score();
else if (part == "sheet_1_underside_score") sheet_1_underside_score();
else if (part == "sheet_2_cut") sheet_2_cut();
else if (part == "sheet_3_cut") sheet_3_cut();
else if (part == "sheet_3_score") sheet_3_score();
else if (part == "sheet_4_reader_holders") sheet_4_reader_holders();
