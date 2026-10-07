# Manual Cleanup Notes

These commands are for a human maintainer only. Agents should not run destructive cleanup commands.

Preview untracked files that Git would remove:

```powershell
git clean -nd
```

Remove untracked files only after reviewing the preview carefully:

```powershell
git clean -f
```