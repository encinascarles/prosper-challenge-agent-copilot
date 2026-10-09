// The agent a "New agent" starts as.
//
// The smallest flow the backend accepts and a call can get through: a start
// node, an end node, and one edge between them. Starting from something valid
// means the first save works and the first test call has somewhere to go; the
// texts are there to be replaced.

import type { AgentConfig } from './types'

export const NEW_AGENT: AgentConfig = {
  name: 'New agent',
  persona:
    'You are a friendly, efficient assistant on a phone call. Your replies are spoken aloud, so keep them to one or two short sentences.',
  initial_node: 'greeting',
  nodes: [
    {
      name: 'greeting',
      task_messages: [{ role: 'developer', content: 'Greet the caller and ask how you can help.' }],
      edges: [
        {
          function: 'go_to_goodbye',
          description: 'Once the caller has said what they need.',
          target: 'goodbye',
        },
      ],
    },
    {
      name: 'goodbye',
      task_messages: [{ role: 'developer', content: 'Thank the caller and say goodbye.' }],
      end: true,
    },
  ],
}
