# Contributing

Contributions to improve the workshop content are welcome.

## How to Contribute

1. Fork this repository
2. Create a feature branch (`git checkout -b improve-module-3`)
3. Make your changes
4. Test any scripts or manifests
5. Submit a pull request

## Content Guidelines

- All examples must work on the specified hardware (P5.48xlarge with EFA)
- Never commit API keys, tokens, or credentials
- Use placeholder markers (`<YOUR_API_KEY>`) for any sensitive values
- Keep module timings realistic - test with an audience if possible
- Include verification steps for every deployment

## Module Structure

Each module follows this pattern:

```
modules/NN-module-name/
  README.md          # Main content with sections
  examples/          # Code examples (optional)
  manifests/         # K8s manifests (optional)
```

## Code of Conduct

Be respectful, constructive, and inclusive.
