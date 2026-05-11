import { Slider, Stack, TextField, Typography } from '@mui/material'

type RangeSliderProps = {
  label: string
  min: number
  max: number
  value: [number | null, number | null]
  onChange: (next: [number, number]) => void
  step?: number
}

export function RangeSlider(props: RangeSliderProps) {
  const { label, min, max, value, onChange, step } = props
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return null

  const lo = value[0] ?? min
  const hi = value[1] ?? max

  const commit = (next: [number, number]) => {
    const a = Math.max(min, Math.min(max, next[0]))
    const b = Math.max(min, Math.min(max, next[1]))
    onChange([Math.min(a, b), Math.max(a, b)])
  }

  return (
    <Stack spacing={1}>
      <Typography variant="body2">{label}</Typography>
      <Slider
        value={[lo, hi]}
        min={min}
        max={max}
        step={step}
        valueLabelDisplay="auto"
        onChangeCommitted={(_, v) => {
          const arr = v as Array<number>
          commit([arr[0], arr[1]])
        }}
      />
      <Stack direction="row" spacing={1}>
        <TextField
          type="number"
          size="small"
          label="min"
          defaultValue={lo}
          key={`min-${lo}`}
          onBlur={(e) => {
            const n = Number(e.target.value)
            if (Number.isFinite(n)) commit([n, hi])
          }}
        />
        <TextField
          type="number"
          size="small"
          label="max"
          defaultValue={hi}
          key={`max-${hi}`}
          onBlur={(e) => {
            const n = Number(e.target.value)
            if (Number.isFinite(n)) commit([lo, n])
          }}
        />
      </Stack>
    </Stack>
  )
}
