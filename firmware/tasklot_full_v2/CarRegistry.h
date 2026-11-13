// CarRegistry.h - which sticker is which car, and the label each car carries.
//
// Role: the board's memory of the cars. A sticker stores nothing; it is a key. The
// registry maps UID -> car index (in the order cars are first seen, shared by all six
// readers, so car 3 is car 3 wherever it parks) and car index -> 18-character label.
// The laptop does the shortening; the registry just stores what it is told.
//
// With REMEMBER 1 the registry is mirrored into EEPROM. Layout:
//   [magic][version][car count] then MAX_CARS x { uid length, uid[10], label[19] }
//   = 3 + 8 * 30 = 243 bytes of the ATmega2560's 4096.
// The magic byte keeps a blank or unrelated EEPROM from loading as eight garbage cars.
// Writes go through EEPROM.update(), which skips bytes that did not change: a cell is
// good for about 100,000 writes and labels change on every event.
//
// Car indexes here are 0-based; the serial protocol shows them 1-based.

#ifndef TASKLOT_CAR_REGISTRY_H
#define TASKLOT_CAR_REGISTRY_H

#include "Uid.h"
#include "config.h"

class CarRegistry {
 public:
  /** Why add() did or did not register a UID. */
  enum AddStatus : byte {
    ADDED,        // registered; the car index is valid
    FULL,         // MAX_CARS cars are already registered
    IMPLAUSIBLE,  // the UID looks like a partial read (Uid::isPlausible)
  };

  /** Result of add(): a status and, when ADDED, the new car index. */
  struct AddResult {
    AddStatus status;
    int8_t car;
  };

  /** What load() found in EEPROM. */
  enum LoadStatus : byte {
    LOAD_DISABLED,       // REMEMBER is 0; nothing is read
    LOAD_NOTHING_SAVED,  // no valid magic/version
    LOAD_BAD_COUNT,      // a header with an impossible car count; ignored
    LOAD_RESTORED,       // count() cars and their labels restored
  };

  /** Starts empty: no cars, every label blank. */
  CarRegistry();

  /**
   * Looks up a UID.
   *
   * Returns: the car index, or NO_CAR if this UID has never been registered.
   */
  int8_t find(const Uid& uid) const;

  /**
   * Registers a UID that find() did not know.
   *
   * The FULL check comes first, so a ninth UID is reported as FULL even if it is also
   * implausible.
   *
   * Returns: {ADDED, index} on success, otherwise {FULL or IMPLAUSIBLE, NO_CAR}.
   * Side effects: with REMEMBER 1, saves the registry to EEPROM.
   */
  AddResult add(const Uid& uid);

  /** Number of registered cars (0..MAX_CARS). */
  byte count() const;

  /** The UID of registered car `car` (0 <= car < count()). */
  const Uid& uidOf(int8_t car) const;

  /** The label of car `car` (0 <= car < MAX_CARS); "" when blank. */
  const char* label(int8_t car) const;

  /** Whether car `car` has a non-empty label. */
  bool hasLabel(int8_t car) const;

  /**
   * Sets car `car`'s label to the first TASK_LEN characters of `text`, byte for byte
   * (no character filtering; the laptop sends ASCII). Works for a car that has not
   * been seen yet, so the laptop can label before the sticker is first read.
   *
   * Params: car - 0 <= car < MAX_CARS; text - NUL-terminated, may be "".
   * Side effects: with REMEMBER 1, saves this car to EEPROM.
   */
  void setLabel(int8_t car, const char* text);

  /** Blanks car `car`'s label. Side effects: with REMEMBER 1, saves this car. */
  void clearLabel(int8_t car);

  /** Blanks every label; UIDs are kept. Side effects: with REMEMBER 1, saves all slots. */
  void clearAllLabels();

  /**
   * Restores the registry from EEPROM (REMEMBER 1 only).
   *
   * Returns: what was found; see LoadStatus.
   * Side effects: replaces the car list and labels on LOAD_RESTORED.
   */
  LoadStatus load();

  /**
   * Invalidates the saved copy so the next boot starts clean (REMEMBER 1 only).
   *
   * Returns: true if persistence is compiled in (and the copy was invalidated),
   *   false if REMEMBER is 0.
   * Side effects: overwrites the magic byte. The in-RAM registry is unchanged.
   */
  bool forget();

 private:
  // EEPROM writers (REMEMBER 1; empty otherwise). All go through EEPROM.update().
  void saveHeader();      // magic, version, car count
  void saveCar(byte car); // one car's UID and label
  void saveAll();         // the header and every registered car

  Uid known_[MAX_CARS];
  char labels_[MAX_CARS][TASK_LEN + 1];
  byte count_;
};

#endif  // TASKLOT_CAR_REGISTRY_H
