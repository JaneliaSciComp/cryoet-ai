import { Box, Typography } from '@mui/material'

export function Footer() {
  return (
    <Box
      component="footer"
      sx={{
        bgcolor: 'primary.main',
        color: 'primary.contrastText',
        px: { xs: 2, md: 4 },
        py: 2,
        textAlign: 'right',
      }}
    >
      <Typography variant="body2">HHMI Janelia</Typography>
    </Box>
  )
}
