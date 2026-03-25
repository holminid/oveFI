export const featureScales = ['micro', 'meso', 'macro'] as const;

export const systemDomains = [
  'musical',
  'visual',
  'social',
  'spatial',
  'behavioral',
  'biosignal',
  'context'
] as const;

export const featureGroups = {
  micro: {
    scope: 'Local musical atoms, gestures, motifs, ornaments, articulation, and rhythmic cells.',
    examples: ['gesture', 'motif', 'ornament', 'articulation', 'rhythmic cell']
  },
  meso: {
    scope: 'Phrase, cadence, ostinato, section texture, accompaniment pattern, and role behavior.',
    examples: ['phrase', 'cadence', 'ostinato', 'section texture', 'accompaniment pattern', 'role behavior']
  },
  macro: {
    scope: 'Formal arcs, section plans, narrative logic, global density, and large-scale coordination.',
    examples: ['formal arc', 'section plan', 'narrative logic', 'global density', 'large-scale coordination']
  },
  systems: {
    scope: 'System domains that a work or resolver node can touch.',
    examples: [...systemDomains]
  }
} as const;

export const allowedLabels = {
  featureScale: featureScales,
  systems: systemDomains,
  relatedTags: [
    'adaptive music',
    'biosignal',
    'cadence',
    'collective behavior',
    'context-aware music',
    'ecological metaphor',
    'generative visuals',
    'gesture',
    'macro form',
    'ostinato',
    'participatory system',
    'texture',
    'voice',
    'voice-leading'
  ]
} as const;

export const mappingNotes = [
  'These handles are shared across work entries, research notes, and future resolver pages.',
  'Use featureScale for structural scope: micro for local atoms and gestures, meso for phrases, cadences, ostinati, and textures, macro for formal arcs and large-scale coordination.',
  'Use systems for the domains involved in a feature: musical, visual, social, spatial, behavioral, biosignal, or context.',
  'The same handle set can be reused in the Telharmonium Composer UI to connect atoms, cadence objects, ostinato types, texture units, and voice-leading objects to related resolver views.'
] as const;
