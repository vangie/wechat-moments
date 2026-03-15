# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-03-15

### Added

- Initial release
- CLI tool `wx-pyq-adb` for posting to WeChat Moments
- MCP server `wx-pyq-adb-mcp` for AI agent integration
- FSM-based UI automation (no LLM required for UI interaction)
- Support for text-only and image posts (up to 9 images)
- Preview generation before posting
- Device profile system for different Android devices
- ADBKeyboard integration for Chinese text input

### Features

- `wx-pyq-adb status` - Check device connection
- `wx-pyq-adb post` - Post to Moments with text and/or images
- `wx-pyq-adb cleanup` - Clean up expired staging/archive directories
- `wx-pyq-adb calibrate` - Create device profile for new devices
- `wx-pyq-adb collect-fixtures` - Collect FSM test fixtures

[Unreleased]: https://github.com/vangie/wechat-moments/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/vangie/wechat-moments/releases/tag/v0.1.0
