import { Box, Chip, Stack, Typography } from '@mui/material'
import type { AnnotationOut } from '~/types'

type AnnotationListProps = {
  annotations: AnnotationOut[]
}

export function AnnotationList(props: AnnotationListProps) {
  const { annotations } = props
  if (annotations.length === 0) return null

  return (
    <Stack spacing={1}>
      <Typography variant="overline">Annotations</Typography>
      {annotations.map((a) => (
        <Box
          key={a.annotation_id}
          sx={{
            display: 'flex',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 1,
          }}
        >
          <Chip size="small" label={a.type ?? 'unknown'} />
          <Typography variant="body2">{a.annotation_id}</Typography>
          {a.files.length > 0 ? (
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ wordBreak: 'break-all' }}
            >
              {a.files.join(' ')}
            </Typography>
          ) : null}
        </Box>
      ))}
    </Stack>
  )
}
