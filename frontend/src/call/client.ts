// A real voice call to the bot, as events for the call reducer (path.ts).
//
// Pipecat's own client over the small WebRTC transport: the same protocol as
// its prebuilt test client at /client. The call is started through the
// runner's /start with the id of the saved agent, so the bot runs what was
// saved (backend/api/calls.py); the runner answers with a session and the
// transport sends its offer there.
//
// Everything that can go wrong before or during the call becomes a `failed`
// event with a sentence a person can act on. Nothing fails silently: a call
// with no sound and no reason is the worst outcome of a test.

import { DeviceError, PipecatClient, StartBotError } from '@pipecat-ai/client-js'
import { SmallWebRTCTransport } from '@pipecat-ai/small-webrtc-transport'

import { isNodeMessage, type CallEvent } from './path'

export type LiveCall = {
  /** Hangs up. The `ended` event follows. */
  end: () => void
}

const MIC_BLOCKED =
  "The microphone is blocked for this page. Allow it in the browser's site settings and try again."
const NO_MIC = 'No microphone was found. Connect one and try again.'
const MIC_FAILED = "The microphone couldn't be used. Check that no other app has it and try again."
const NOT_STARTED = "The call couldn't start. Check that the server is running and try again."
const NOT_CONNECTED = "The call didn't connect. Try again."

function micProblem(error: DeviceError): string {
  if (error.type === 'permissions') return MIC_BLOCKED
  if (error.type === 'not-found') return NO_MIC
  // An insecure origin has no microphone to ask for at all.
  if (error.type === 'undefined-mediadevices') {
    return 'This page cannot use the microphone: open it over HTTPS or on localhost.'
  }
  return MIC_FAILED
}

/** Starts a call to the saved agent `agentId`, reporting what happens to `emit`. */
export function startCall(agentId: string, emit: (event: CallEvent) => void): LiveCall {
  // Once over, a call says nothing more: the client keeps firing callbacks
  // while it tears down, and a failure is followed by its own disconnect.
  let over = false
  // Whether the runner took the start: what fails after that is the connection.
  let started = false
  const finish = (event: CallEvent) => {
    if (over) return
    over = true
    emit(event)
    audio.srcObject = null
    // Also on a failure: a client left half connected would keep the microphone.
    void client.disconnect().catch(() => {})
  }
  const fail = (problem: string) => finish({ type: 'failed', problem, now: Date.now() })
  const send = (event: CallEvent) => {
    if (!over) emit(event)
  }

  // The bot's voice. The transport hands over the track; playing it is ours.
  const audio = new Audio()
  audio.autoplay = true

  const client = new PipecatClient({
    transport: new SmallWebRTCTransport(),
    enableMic: true,
    enableCam: false,
    callbacks: {
      onBotStarted: () => {
        started = true
      },
      onBotReady: () => send({ type: 'ready', now: Date.now() }),
      onServerMessage: (data: unknown) => {
        if (isNodeMessage(data)) send({ type: 'node', message: data, now: Date.now() })
      },
      // What the model writes, as it writes it: one line per answer. It is on
      // screen a moment before it is heard, and all of it even if the caller
      // cuts in, which for reading a test is the more useful of the two.
      onBotLlmStarted: () => send({ type: 'agent-turn' }),
      onBotLlmText: (data) => send({ type: 'agent-text', text: data.text }),
      onUserTranscript: (data) => {
        if (data.final) send({ type: 'caller-text', text: data.text })
      },
      onTrackStarted: (track, participant) => {
        if (track.kind === 'audio' && !participant?.local) {
          audio.srcObject = new MediaStream([track])
          void audio.play().catch(() => {})
        }
      },
      onDeviceError: (error) => fail(micProblem(error)),
      onError: (message) => {
        const data = message.data as { message?: unknown; error?: unknown; fatal?: unknown } | undefined
        if (!data?.fatal) return
        const said = data.message ?? data.error
        fail(typeof said === 'string' && said ? said : NOT_CONNECTED)
      },
      // The bot hung up (an end node) or the caller did: the call is over.
      onDisconnected: () => finish({ type: 'ended', now: Date.now() }),
    },
  })

  void (async () => {
    try {
      // Asked for first and on its own, so a blocked microphone is known
      // before a bot is started for a call nobody can speak in.
      await client.initDevices()
      if (over) return
      await client.startBotAndConnect({
        endpoint: '/start',
        requestData: {
          transport: 'webrtc',
          // A STUN server, so the call also connects from another device.
          enableDefaultIceServers: true,
          body: { agent_id: agentId },
        },
      })
    } catch (error) {
      if (error instanceof DeviceError) fail(micProblem(error))
      // The backend's own sentence when it refused the start ("No agent with id ...").
      else if (error instanceof StartBotError && error.status && error.status < 500) fail(error.message)
      // No answer from the runner, or a proxy's error page in its place.
      else fail(started ? NOT_CONNECTED : NOT_STARTED)
    }
  })()

  return { end: () => finish({ type: 'ended', now: Date.now() }) }
}
