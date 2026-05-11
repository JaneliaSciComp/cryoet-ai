import { Box, Card, CardContent, Stack, Typography } from '@mui/material'

type SubEntityBlockProps = {
  title: string
  entries: Array<[string, unknown]>
}

function isEmpty(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string' && value === '') return true
  if (Array.isArray(value) && value.length === 0) return true
  return false
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((v) => String(v)).join(' ')
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value)
}

export function SubEntityBlock(props: SubEntityBlockProps) {
  const { title, entries } = props
  const filtered = entries.filter(([, v]) => !isEmpty(v))
  if (filtered.length === 0) return null

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="overline" component="div" sx={{ mb: 1 }}>
          {title}
        </Typography>
        <Stack spacing={0.5}>
          {filtered.map(([label, value]) => (
            <Box key={label} sx={{ display: 'flex', gap: 1 }}>
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{ minWidth: 180 }}
              >
                {label}:
              </Typography>
              <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>
                {formatValue(value)}
              </Typography>
            </Box>
          ))}
        </Stack>
      </CardContent>
    </Card>
  )
}
