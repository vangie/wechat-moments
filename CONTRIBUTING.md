# Contributing to wechat-moments

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Development Setup

1. Clone the repository:

```bash
git clone https://github.com/vangie/wechat-moments
cd wechat-moments
```

2. Install dependencies with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

3. Run tests:

```bash
uv run pytest tests/unit tests/fsm -v
```

## Code Style

- Use [ruff](https://docs.astral.sh/ruff/) for linting and formatting
- Follow PEP 8 conventions
- Write docstrings for public functions
- Keep comments in English

## Testing

- Unit tests go in `tests/unit/`
- FSM state identification tests go in `tests/fsm/`
- End-to-end tests (requiring a phone) go in `tests/e2e/` and are marked with `@pytest.mark.e2e`

Run tests before submitting:

```bash
uv run pytest tests/unit tests/fsm -q
```

## Pull Request Process

1. Fork the repository and create a feature branch from `main`
2. Make your changes with clear, descriptive commits
3. Add tests for new functionality
4. Ensure all tests pass
5. Update documentation if needed
6. Submit a PR with a clear description of changes

## Reporting Issues

When reporting bugs, please include:

- Python version (`python --version`)
- OS and version
- Device model (if device-related)
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs or screenshots

## Questions?

Feel free to open an issue for questions or discussions.
