// ReadbackText.cpp - chunk collection and word wrap for read-backs. See ReadbackText.h.

#include "ReadbackText.h"

ReadbackText::ReadbackText() : length_(0), rowCount_(0) { text_[0] = '\0'; }

void ReadbackText::clearText() {
  length_ = 0;
  text_[0] = '\0';
}

void ReadbackText::clearAll() {
  clearText();
  rowCount_ = 0;
}

void ReadbackText::append(const char* chunk) {
  if (length_ && length_ < FULL_LEN) text_[length_++] = ' ';
  while (*chunk && length_ < FULL_LEN) text_[length_++] = *chunk++;
  text_[length_] = '\0';
}

void ReadbackText::wrap() {
  rowCount_ = 0;
  byte i = 0;
  while (text_[i] && rowCount_ < WRAP_LINES) {
    byte take = 0;
    byte lastSpace = 0;
    while (take < LCD_COLS && text_[i + take]) {
      if (text_[i + take] == ' ') lastSpace = take;
      take++;
    }
    // More text follows: break at the last space in the row, if there was one.
    if (text_[i + take] && lastSpace) take = lastSpace;

    byte j = 0;
    for (; j < take; j++) rows_[rowCount_][j] = text_[i + j];
    rows_[rowCount_][j] = '\0';
    rowCount_++;

    i += take;
    while (text_[i] == ' ') i++;
  }
}

byte ReadbackText::rowCount() const { return rowCount_; }

const char* ReadbackText::row(byte index) const { return rows_[index]; }
