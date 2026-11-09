package com.example;

import com.code_intelligence.jazzer.junit.FuzzTest;

class AppFuzzTest {
  @FuzzTest
  void addNeverThrows(byte[] data) {
    App.add(data.length, data.length);
  }
}
