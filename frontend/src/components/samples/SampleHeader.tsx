import { Chip, Stack, Typography } from '@mui/material'
import type { SampleDetail } from '~/types'

type SampleHeaderProps = {
  sample: SampleDetail
  warningCount: number
}

export function SampleHeader(props: SampleHeaderProps) {
  const { sample, warningCount } = props
  return (
    <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
      <Typography variant="h5">
        {sample.project} / {sample.sample_id}
      </Typography>
      {sample.type ? <Chip size="small" label={sample.type} /> : null}
      {warningCount > 0 ? (
        <Chip
          size="small"
          color="warning"
          label={`${warningCount} warning${warningCount === 1 ? '' : 's'}`}
        />
      ) : null}
    </Stack>
  )
}
