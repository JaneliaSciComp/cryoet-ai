import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  Stack,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import type { WarningOut } from '~/types'

type WarningListProps = {
  warnings: WarningOut[]
}

export function WarningList(props: WarningListProps) {
  const { warnings } = props
  if (warnings.length === 0) return null

  return (
    <Accordion defaultExpanded={false}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography>
          {warnings.length} warning{warnings.length === 1 ? '' : 's'}
        </Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={1}>
          {warnings.map((w) => (
            <Box
              key={w.id}
              sx={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 1,
                flexWrap: 'wrap',
              }}
            >
              <Chip size="small" label={w.category} />
              <Typography variant="body2" color="text.secondary">
                {w.location}
              </Typography>
              <Typography variant="body2">{w.message}</Typography>
            </Box>
          ))}
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}
