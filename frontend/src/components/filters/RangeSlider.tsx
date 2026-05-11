import { useEffect, useState } from 'react'
import { Slider, Stack, TextField, Typography } from '@mui/material'

type RangeSliderProps = {
  label: string
  min: number
  max: number
  value: [number | null, number | null]
  onChange: (next: [number, number]) => void
  step?: number
}

// Debounce between an input edit and committing to the parent. Lets the user
// click the number-input spinner buttons (which fire onChange immediately)
// without paying a URL-navigate per click, and lets them type a multi-digit
// number without each keystroke clamping the value.
const COMMIT_DEBOUNCE_MS = 200

export function RangeSlider(props: RangeSliderProps) {
  const { label, min, max, value, onChange, step } = props
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return null

  const externalLo = value[0] ?? min
  const externalHi = value[1] ?? max

  const [draftLo, setDraftLo] = useState(externalLo)
  const [draftHi, setDraftHi] = useState(externalHi)

  // Resync drafts when the external value changes (parent clears filters,
  // shared URL deserializes, etc.). Keep the two dimensions in separate
  // effects so a change to only one bound doesn't reset the other's in-flight
  // edit.
  useEffect(() => {
    setDraftLo(externalLo)
  }, [externalLo])
  useEffect(() => {
    setDraftHi(externalHi)
  }, [externalHi])

  // Debounced commit: any draft change (slider drag, spinner click, typing)
  // settles into a single `onChange` call after COMMIT_DEBOUNCE_MS of quiet.
  useEffect(() => {
    if (draftLo === externalLo && draftHi === externalHi) return
    const id = setTimeout(() => {
      const a = Math.max(min, Math.min(max, draftLo))
      const b = Math.max(min, Math.min(max, draftHi))
      onChange([Math.min(a, b), Math.max(a, b)])
    }, COMMIT_DEBOUNCE_MS)
    return () => clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftLo, draftHi])

  return (
    <Stack spacing={1}>
      <Typography variant="body2">{label}</Typography>
      <Slider
        value={[draftLo, draftHi]}
        min={min}
        max={max}
        step={step}
        valueLabelDisplay="auto"
        onChange={(_, v) => {
          const arr = v as Array<number>
          setDraftLo(arr[0])
          setDraftHi(arr[1])
        }}
      />
      <Stack direction="row" spacing={1}>
        <TextField
          type="number"
          size="small"
          label="min"
          value={draftLo}
          onChange={(e) => {
            const n = Number(e.target.value)
            if (Number.isFinite(n)) setDraftLo(n)
          }}
        />
        <TextField
          type="number"
          size="small"
          label="max"
          value={draftHi}
          onChange={(e) => {
            const n = Number(e.target.value)
            if (Number.isFinite(n)) setDraftHi(n)
          }}
        />
      </Stack>
    </Stack>
  )
}
