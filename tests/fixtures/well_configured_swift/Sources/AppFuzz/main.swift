import AppCore

@_cdecl("LLVMFuzzerTestOneInput")
public func fuzzOneInput(_ data: UnsafePointer<UInt8>, _ size: Int) -> CInt {
    _ = Calculator.add(size, size)
    return 0
}
