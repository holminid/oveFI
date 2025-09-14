import { defineCollection, z } from 'astro:content';

const works = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    date: z.string().optional(),         // keep as string
    summary: z.string().optional(),
    videoUrl: z.string().url().optional(),
    aspect: z.enum(['16:9', '4:3']).default('16:9').optional(),
    draft: z.boolean().default(false).optional(),
  }),
});

const bio = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    date: z.string().optional(),         // keep as string
  }),
});

export const collections = { works, bio };
