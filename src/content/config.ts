import { defineCollection, z } from 'astro:content';
import { featureScales, systemDomains } from '../data/feature-taxonomy';

const dateSchema = z.preprocess((value) => {
  if (value instanceof Date) {
    return value.toISOString().slice(0, 10);
  }

  return value;
}, z.string());

const aspectSchema = z.preprocess((value) => {
  if (typeof value === 'number') {
    if (value === 969) return '16:9';
    if (value === 243) return '4:3';
  }

  return value;
}, z.enum(['16:9', '4:3']));

const imageSchema = z.object({
  src: z.string(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  alt: z.string(),
  caption: z.string().optional()
});

const videoSchema = z.object({
  src: z.string(),
  poster: z.string().optional(),
  aspect: aspectSchema.default('16:9'),
  captions: z.array(z.object({ src: z.string(), srclang: z.string(), label: z.string(), default: z.boolean().optional() })).optional()
});

const externalVideoSchema = z.object({
  kind: z.literal('youtube'),
  id: z.string(),
  title: z.string().optional(),
  aspect: aspectSchema.default('16:9')
});

const works = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    date: dateSchema,
    location: z.string().optional(),
    mediaType: z.enum(['photo', 'video', 'mixed']).default('mixed'),
    cover: imageSchema,
    images: z.array(imageSchema).default([]),
    videos: z.array(videoSchema).default([]),
    externalVideos: z.array(externalVideoSchema).default([]),
    summary: z.string().optional(),
    relatedTags: z.array(z.string()).optional(),
    featureScale: z.array(z.enum(featureScales)).optional(),
    systems: z.array(z.enum(systemDomains)).optional()
  })
});

const bio = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    date: dateSchema,
    summary: z.string().optional(),
    cover: imageSchema.optional(),
    relatedTags: z.array(z.string()).optional(),
  })
});

export const collections = { works, bio };
