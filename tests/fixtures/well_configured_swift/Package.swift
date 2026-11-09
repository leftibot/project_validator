// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "App",
    dependencies: [
        .package(url: "https://github.com/apple/swift-argument-parser", from: "1.5.0"),
    ],
    targets: [
        .target(name: "AppCore"),
        .executableTarget(
            name: "App",
            dependencies: ["AppCore", .product(name: "ArgumentParser", package: "swift-argument-parser")]
        ),
        .executableTarget(name: "AppFuzz", dependencies: ["AppCore"]),
        .testTarget(name: "AppCoreTests", dependencies: ["AppCore"]),
    ]
)
