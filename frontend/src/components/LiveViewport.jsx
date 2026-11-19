import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Eye,
  Globe2,
  Maximize2,
  Minimize2,
  MousePointer2,
  Pause,
  Play,
  Power,
  Radio,
  RefreshCw,
  ScanSearch,
  Shield,
  ShieldCheck,
  Sparkles,
  Unplug,
  Wifi,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';

import { getWsUrl } from '../apiConfig';

function wsUrlFor(path) {
  return getWsUrl(path);
}

function displayUrl(url) {
  const value = String(url || '');
  if (!value) return '';
  try {
    const parsed = new URL(value);
    return `${parsed.host}${parsed.pathname}${parsed.search ? '?' + parsed.search.slice(1) : ''}`;
  } catch {
    return value;
  }
}

export default function LiveViewport({
  screenshot,
  liveSession,
  agentRunning,
  currentSection,
  onStop,
  onRescan,
  onPauseToggle,
  onPractice,
  runMode,
  runState,
  paused,
  takeover,
  onTakeover,
  onReturnControl,
  pendingGate,
  onOpenGate,
  className = '',
}) {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [frame, setFrame] = useState('');
  const [viewport, setViewport] = useState({ width: 1280, height: 800 });
  const [pageInfo, setPageInfo] = useState({ url: '', title: '' });
  const [zoom, setZoom] = useState(100);
  const [control, setControl] = useState({
    enabled: runMode === 'inspect',
    reason: runMode === 'inspect'
      ? 'Inspect mode: the browser is yours.'
      : 'The agent is driving. You can take over when it pauses.',
  });
  const [connected, setConnected] = useState(false);
  const [inputError, setInputError] = useState('');
  const [frameCount, setFrameCount] = useState(0);
  const [address, setAddress] = useState('');
  const [rescanning, setRescanning] = useState(false);
  // A phone keyboard cannot type into a streamed image, so this box forwards
  // what the candidate types into the focused field of the real page.
  const [typing, setTyping] = useState('');
  const [somMarks, setSomMarks] = useState([]);
  const [showSom, setShowSom] = useState(false);
  const [somLoading, setSomLoading] = useState(false);
  const [smartFilling, setSmartFilling] = useState(false);
  const [somMessage, setSomMessage] = useState('');

  const wsRef = useRef(null);
  const imageRef = useRef(null);
  const shellRef = useRef(null);
  // Touch support: a phone has no mouse, so taps must become clicks and a
  // sideways drag must become a mouse drag.  `lastTouchRef` suppresses the
  // synthetic mouse events Chrome fires after a touch, which would otherwise
  // double every tap.
  const lastTouchRef = useRef(0);
  const touchRef = useRef({
    active: false,
    dragging: false,
    startX: 0,
    startY: 0,
    lastX: 0,
    lastY: 0,
    pinch: 0,
    zoomStart: 100,
  });
  const touchHandlersRef = useRef({});
  const reconnectRef = useRef(null);
  const errorTimerRef = useRef(null);
  const moveRef = useRef({ pending: null, lastSent: 0, raf: null });
  // A page/frame update must not overwrite an address the human is typing.
  const addressEditingRef = useRef(false);
  const wsPath = liveSession?.ws_path || '';

  const flashError = useCallback((message) => {
    setInputError(String(message || 'The live browser could not accept that input.'));
    if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
    errorTimerRef.current = setTimeout(() => setInputError(''), 5000);
  }, []);

  // Connect to the same Chromium page the agent is driving.
  useEffect(() => {
    if (!wsPath) {
      setConnected(false);
      setFrame('');
      return undefined;
    }

    let disposed = false;
    let stopReconnect = false;
    let attempts = 0;
    addressEditingRef.current = false;
    setFrame('');
    setFrameCount(0);
    setControl({
      enabled: runMode === 'inspect',
      reason: runMode === 'inspect'
        ? 'Inspect mode: the browser is yours.'
        : 'The agent is driving. You can take over when it pauses.',
    });

    const connect = () => {
      if (disposed) return;
      let socket;
      try {
        socket = new WebSocket(wsUrlFor(wsPath));
      } catch {
        flashError('The live browser address is not valid.');
        return;
      }
      wsRef.current = socket;

      socket.onopen = () => {
        if (disposed) return;
        setConnected(true);
      };

      socket.onmessage = (event) => {
        if (disposed) return;
        let data;
        try {
          data = JSON.parse(event.data);
        } catch {
          return;
        }
        if (data.type === 'hello') {
          setConnected(true);
          setViewport(data.viewport || { width: 1280, height: 800 });
          setPageInfo({ url: data.url || '', title: data.title || '' });
          setControl({
            enabled: Boolean(data.control_enabled),
            reason: data.control_reason || '',
          });
          if (data.url && !addressEditingRef.current) setAddress(data.url);
          return;
        }
        if (data.type === 'frame' && data.data) {
          setFrame(`data:image/jpeg;base64,${data.data}`);
          if (data.viewport) setViewport(data.viewport);
          if (data.frames_sent !== undefined) setFrameCount(data.frames_sent);
          if (data.url) {
            setPageInfo((previous) => (
              previous.url === data.url ? previous : { ...previous, url: data.url }
            ));
          }
          return;
        }
        if (data.type === 'page') {
          setPageInfo({
            url: data.url || '',
            title: data.title || '',
          });
          if (data.viewport) setViewport(data.viewport);
          if (data.url && !addressEditingRef.current) setAddress(data.url);
          return;
        }
        if (data.type === 'control') {
          setControl({
            enabled: Boolean(data.enabled),
            reason: data.reason || '',
          });
          return;
        }
        if (data.type === 'input_error') {
          flashError(data.error || 'The live browser did not accept that input.');
          if (data.control_enabled === false && data.error) {
            setControl((previous) => ({ ...previous, enabled: false, reason: data.error }));
          }
          return;
        }
        if (data.type === 'closed') {
          stopReconnect = true;
          setConnected(false);
          setControl({ enabled: false, reason: data.message || 'The live session ended.' });
        }
      };

      socket.onclose = () => {
        if (disposed || stopReconnect) return;
        setConnected(false);
        attempts += 1;
        if (attempts > 5) {
          flashError('The live browser connection was lost. Start the portal again or stop the run.');
          return;
        }
        // The session registry may still have the page while a gate is open.
        // Retry a few times rather than dropping the human's view.
        if (reconnectRef.current) clearTimeout(reconnectRef.current);
        reconnectRef.current = setTimeout(() => {
          if (!disposed) connect();
        }, 1800);
      };

      socket.onerror = () => {
        setConnected(false);
      };
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          // ignore
        }
      }
      wsRef.current = null;
      if (moveRef.current.raf) clearTimeout(moveRef.current.raf);
      moveRef.current = { pending: null, lastSent: 0, raf: null };
      if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
    };
  }, [wsPath, runMode, flashError]);

  const send = useCallback((payload) => {
    const socket = wsRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      flashError('The live browser is reconnecting. Try again in a moment.');
      return false;
    }
    try {
      socket.send(JSON.stringify(payload));
      return true;
    } catch {
      flashError('The live browser could not accept that input.');
      return false;
    }
  }, [flashError]);

  const pagePoint = (event) => {
    const image = imageRef.current;
    if (!image) return null;
    const rect = image.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = ((event.clientX - rect.left) / rect.width) * viewport.width;
    const y = ((event.clientY - rect.top) / rect.height) * viewport.height;
    if (x < 0 || y < 0 || x > viewport.width || y > viewport.height) return null;
    return { x: Math.round(x), y: Math.round(y) };
  };

  const modifiersOf = (event) => ({
    altKey: event.altKey,
    ctrlKey: event.ctrlKey,
    metaKey: event.metaKey,
    shiftKey: event.shiftKey,
  });

  const sendMouse = (event, kind) => {
    if (!control.enabled) return;
    const point = pagePoint(event);
    if (!point) return;
    send({
      type: 'mouse',
      event: kind,
      x: point.x,
      y: point.y,
      button: event.button === 2 ? 'right' : event.button === 1 ? 'middle' : 'left',
      ...modifiersOf(event),
    });
  };

  const handleMouseMove = (event) => {
    if (!control.enabled) return;
    const point = pagePoint(event);
    if (!point) return;
    const state = moveRef.current;
    state.pending = point;
    const now = performance.now();
    if (state.raf) return;
    const wait = Math.max(0, 34 - (now - state.lastSent));
    state.raf = setTimeout(() => {
      state.raf = null;
      const current = moveRef.current.pending;
      if (!current) return;
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      wsRef.current.send(JSON.stringify({ type: 'mouse', event: 'move', x: current.x, y: current.y }));
      moveRef.current.lastSent = performance.now();
    }, wait);
  };

  const handleWheel = useCallback((event) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    const point = pagePoint(event);
    if (!point) return;
    event.preventDefault();
    send({
      type: 'wheel',
      x: point.x,
      y: point.y,
      deltaX: event.deltaX,
      deltaY: event.deltaY,
      ...modifiersOf(event),
    });
  }, [send, viewport.width, viewport.height]);

  useEffect(() => {
    const node = shellRef.current;
    if (!node) return undefined;
    node.addEventListener('wheel', handleWheel, { passive: false });
    return () => node.removeEventListener('wheel', handleWheel);
  }, [handleWheel]);

  // ------------------------------------------------------------------ touch
  const fromTouch = () => Date.now() - lastTouchRef.current < 800;

  const touchPoint = (touch) => ({
    clientX: touch.clientX,
    clientY: touch.clientY,
    button: 0,
    altKey: false,
    ctrlKey: false,
    metaKey: false,
    shiftKey: false,
  });

  const handleTouchStart = (event) => {
    lastTouchRef.current = Date.now();
    if (!control.enabled) return;
    if (event.touches.length === 2) {
      const [a, b] = event.touches;
      touchRef.current.pinch = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      touchRef.current.zoomStart = zoom;
      touchRef.current.active = false;
      return;
    }
    if (event.touches.length !== 1) return;
    const touch = event.touches[0];
    touchRef.current = {
      ...touchRef.current,
      active: true,
      dragging: false,
      startX: touch.clientX,
      startY: touch.clientY,
      lastX: touch.clientX,
      lastY: touch.clientY,
      pinch: 0,
    };
  };

  const handleTouchMove = (event) => {
    lastTouchRef.current = Date.now();
    if (!control.enabled) return;

    if (event.touches.length === 2 && touchRef.current.pinch > 0) {
      const [a, b] = event.touches;
      const distance = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      if (distance > 0) {
        event.preventDefault();
        const next = touchRef.current.zoomStart * (distance / touchRef.current.pinch);
        setZoom(Math.max(50, Math.min(200, Math.round(next / 5) * 5)));
      }
      return;
    }

    if (!touchRef.current.active || event.touches.length !== 1) return;
    const touch = event.touches[0];
    const state = touchRef.current;
    const dx = touch.clientX - state.startX;
    const dy = touch.clientY - state.startY;
    state.lastX = touch.clientX;
    state.lastY = touch.clientY;

    // A mostly-horizontal drag is a real drag on the page (sliders, selecting
    // text).  A mostly-vertical swipe stays a scroll, which is what a thumb
    // expects on a long form.
    if (!state.dragging && Math.abs(dx) > 14 && Math.abs(dx) > Math.abs(dy) * 1.2) {
      state.dragging = true;
      sendMouse(touchPoint({ clientX: state.startX, clientY: state.startY }), 'down');
    }
    if (state.dragging) {
      event.preventDefault();
      handleMouseMove(touchPoint(touch));
    }
  };

  const handleTouchEnd = (event) => {
    lastTouchRef.current = Date.now();
    const state = touchRef.current;
    if (event.touches.length > 0) return;

    if (state.dragging) {
      sendMouse(touchPoint({ clientX: state.lastX, clientY: state.lastY }), 'up');
    } else if (state.active) {
      const touch = event.changedTouches?.[0];
      if (touch) {
        // A tap is a click.  The page never sees a dangling mouse-down because
        // down and up are sent together.
        sendMouse(touchPoint(touch), 'down');
        window.setTimeout(() => sendMouse(touchPoint(touch), 'up'), 40);
      }
    }
    state.active = false;
    state.dragging = false;
    state.pinch = 0;
  };

  touchHandlersRef.current = {
    start: handleTouchStart,
    move: handleTouchMove,
    end: handleTouchEnd,
  };

  useEffect(() => {
    const node = shellRef.current;
    if (!node) return undefined;
    const start = (event) => touchHandlersRef.current.start?.(event);
    const move = (event) => touchHandlersRef.current.move?.(event);
    const end = (event) => touchHandlersRef.current.end?.(event);
    node.addEventListener('touchstart', start, { passive: true });
    // Non-passive so a horizontal drag or a pinch can stop the page from
    // scrolling underneath it.
    node.addEventListener('touchmove', move, { passive: false });
    node.addEventListener('touchend', end, { passive: true });
    node.addEventListener('touchcancel', end, { passive: true });
    return () => {
      node.removeEventListener('touchstart', start);
      node.removeEventListener('touchmove', move);
      node.removeEventListener('touchend', end);
      node.removeEventListener('touchcancel', end);
    };
  }, []);

  const forwardTyping = (next) => {
    const previous = typing;
    if (next.length >= previous.length) {
      const added = next.slice(previous.length);
      for (const character of added) {
        send({ type: 'key', event: 'down', key: character, code: '', text: character });
        send({ type: 'key', event: 'up', key: character, code: '' });
      }
    } else {
      for (let index = 0; index < previous.length - next.length; index += 1) {
        send({ type: 'key', event: 'down', key: 'Backspace', code: 'Backspace' });
        send({ type: 'key', event: 'up', key: 'Backspace', code: 'Backspace' });
      }
    }
    setTyping(next);
  };

  const pressKey = (key, code = key) => {
    send({ type: 'key', event: 'down', key, code });
    send({ type: 'key', event: 'up', key, code });
  };

  const handleKeyDown = (event) => {
    if (!control.enabled || event.isComposing) return;
    if (event.key === 'F5' || event.key === 'F12') return;
    event.preventDefault();
    send({
      type: 'key',
      event: 'down',
      key: event.key,
      code: event.code,
      text: event.key.length === 1 ? event.key : undefined,
      ...modifiersOf(event),
    });
  };

  const handleKeyUp = (event) => {
    if (!control.enabled || event.isComposing) return;
    if (event.key === 'F5' || event.key === 'F12') return;
    event.preventDefault();
    send({
      type: 'key',
      event: 'up',
      key: event.key,
      code: event.code,
      ...modifiersOf(event),
    });
  };

  const handlePaste = (event) => {
    if (!control.enabled) return;
    const text = event.clipboardData?.getData('text');
    if (!text) return;
    event.preventDefault();
    send({ type: 'paste', text });
  };

  const requestControl = () => {
    send({ type: 'control_request' });
  };

  const navigate = (kind, extra = {}) => {
    send({ type: kind, ...extra });
  };

  const submitAddress = (event) => {
    event.preventDefault();
    const value = address.trim();
    if (!value) return;
    const url = /^https?:\/\//i.test(value) ? value : `https://${value}`;
    // Keep the human's address visible while the navigation is in flight.
    addressEditingRef.current = false;
    setAddress(url);
    navigate('navigate', { url });
  };

  const handleRescan = async () => {
    if (!onRescan || rescanning) return;
    setRescanning(true);
    try {
      await onRescan();
    } finally {
      setRescanning(false);
    }
  };

  const handleSomScan = async () => {
    setSomLoading(true);
    setSomMessage('Scanning interactive elements (Set-of-Marks)…');
    try {
      const res = await fetch('/api/agent/som/scan', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        setSomMarks(data.elements || []);
        setShowSom(true);
        setSomMessage(`Tagged ${data.count} visual marks.`);
      } else {
        setSomMessage('Scan failed.');
      }
    } catch (err) {
      console.error('SOM scan error:', err);
      setSomMessage('Scan error.');
    } finally {
      setSomLoading(false);
    }
  };

  const handleSmartFill = async () => {
    setSmartFilling(true);
    setSomMessage('Gemini Flash reasoning & auto-filling fields…');
    try {
      const res = await fetch('/api/agent/som/step', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        setSomMessage(data.message || `Filled ${data.actions_executed?.length || 0} fields.`);
        await handleSomScan();
      } else {
        setSomMessage(data.message || 'Validation error detected.');
      }
    } catch (err) {
      console.error('Smart fill error:', err);
      setSomMessage('Error during smart fill.');
    } finally {
      setSmartFilling(false);
    }
  };

  const imageSource = frame || screenshot;
  const live = Boolean(wsPath);
  const canControl = Boolean(connected && control.enabled);
  const active = agentRunning || runState === 'WAITING_FOR_USER';
  const finished = ['STOPPED', 'FAILED', 'COMPLETED', 'DONE'].includes(runState);
  const sessionLabel = runMode === 'inspect'
    ? 'INSPECT · NOTHING WILL BE FILLED'
    : finished
      ? runState === 'DONE'
        ? 'SIGNED IN · BROWSER CLOSED'
        : 'SESSION FINISHED · BROWSER CLOSED'
      : runState === 'AWAITING_PAYMENT'
        ? 'YOUR REVIEW · NOTHING SUBMITTED'
        : takeover?.active
          ? 'HUMAN CONTROL · FORMPILOT PAUSED'
          : active
            ? 'AGENT SESSION · HUMAN TAKEOVER AVAILABLE ANY TIME'
            : 'LIVE PORTAL VIEW';

  return (
    <div
      className={`glass-panel specular-top rounded-2xl flex flex-col overflow-hidden shadow-2xl ${
        isFullscreen ? 'fixed inset-2 z-50 bg-[#0d1210]/95 backdrop-blur-2xl border-indigo-500/50 md:inset-4' : className || 'h-[640px]'
      }`}
    >
      {/* Browser chrome */}
      <div className="bg-white/[0.02] px-2.5 sm:px-3 py-2 border-b border-white/[0.08] shrink-0">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className="flex items-center gap-1.5 shrink-0">
              <span className="w-2.5 h-2.5 rounded-full bg-red-500/80" />
              <span className="w-2.5 h-2.5 rounded-full bg-amber-500/80" />
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80" />
            </div>
            <span className="text-slate-600 font-mono text-xs shrink-0">|</span>
            <Radio className={`w-3.5 h-3.5 shrink-0 ${connected ? 'text-emerald-400 animate-pulse' : 'text-slate-500'}`} />
            <span className="text-[11px] font-semibold text-slate-300 font-mono tracking-wide truncate max-w-[130px] sm:max-w-none">
              {sessionLabel}
            </span>
            {runMode !== 'inspect' && (active || live) && (
              <span className="text-[10px] font-bold px-1.5 sm:px-2 py-0.5 rounded-full bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 shrink-0">
                <span className="hidden sm:inline">Section </span>S{currentSection || 1}
              </span>
            )}
          </div>

          <div className="flex items-center gap-1.5 shrink-0 overflow-x-auto no-scrollbar py-0.5 max-w-full">
            {live && (
              <>
                <button
                  type="button"
                  onClick={() => {
                    if (!showSom && somMarks.length === 0) {
                      handleSomScan();
                    } else {
                      setShowSom(!showSom);
                    }
                  }}
                  disabled={somLoading}
                  className={`flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-xl border text-[11px] font-bold transition-all shrink-0 ${
                    showSom
                      ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50 shadow-sm shadow-cyan-500/20'
                      : 'bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 border-slate-700'
                  }`}
                  title="Toggle Set-of-Marks AI visual marks and bounding boxes"
                >
                  <Eye className={`w-3.5 h-3.5 ${somLoading ? 'animate-spin' : ''}`} />
                  <span>{somLoading ? 'Scanning…' : showSom ? `Marks (${somMarks.length})` : 'Marks'}</span>
                </button>

                <button
                  type="button"
                  onClick={handleSmartFill}
                  disabled={smartFilling}
                  className="flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-xl bg-gradient-to-r from-indigo-500/25 to-purple-500/25 hover:from-indigo-500/35 hover:to-purple-500/35 text-indigo-300 border border-indigo-500/50 text-[11px] font-bold transition-all disabled:opacity-50 shadow-sm shadow-indigo-500/20 shrink-0"
                  title="Auto-fill form inputs using Gemini Flash and verify step"
                >
                  <Sparkles className={`w-3.5 h-3.5 ${smartFilling ? 'animate-pulse text-amber-300' : 'text-indigo-400'}`} />
                  <span>
                    <span className="hidden sm:inline">{smartFilling ? 'Filling…' : 'Gemini Fill'}</span>
                    <span className="sm:hidden">{smartFilling ? '…' : 'Fill'}</span>
                  </span>
                </button>
              </>
            )}
            {live && runMode === 'inspect' && (
              <button
                type="button"
                onClick={handleRescan}
                disabled={rescanning}
                className="flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-xl bg-sky-500/15 hover:bg-sky-500/25 text-sky-300 border border-sky-500/40 text-[11px] font-bold transition-all disabled:opacity-50 shrink-0"
                title="Read this page again and update the form map"
              >
                <ScanSearch className={`w-3.5 h-3.5 ${rescanning ? 'animate-pulse' : ''}`} />
                <span>{rescanning ? '…' : 'Rescan'}</span>
              </button>
            )}
            {takeover?.available && runMode !== 'inspect' && (
              takeover.active ? (
                <button
                  type="button"
                  onClick={onReturnControl}
                  className="flex items-center gap-1.5 rounded-xl border border-sky-500/40 bg-sky-500/15 px-2 sm:px-2.5 py-1 text-[11px] font-bold text-sky-300 transition-all hover:bg-sky-500/25 shrink-0"
                  title="Take the page back, re-read it, and stay paused until you continue"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  <span>
                    <span className="hidden sm:inline">Return &amp; rescan</span>
                    <span className="sm:hidden">Return</span>
                  </span>
                </button>
              ) : (
                <button
                  type="button"
                  onClick={onTakeover}
                  className="flex items-center gap-1.5 rounded-xl border border-amber-500/40 bg-amber-500/15 px-2 sm:px-2.5 py-1 text-[11px] font-bold text-amber-300 transition-all hover:bg-amber-500/25 shrink-0"
                  title="Pause FormPilot and control the real page yourself"
                >
                  <MousePointer2 className="h-3.5 w-3.5" />
                  <span>
                    <span className="hidden sm:inline">Take over</span>
                    <span className="sm:hidden">Takeover</span>
                  </span>
                </button>
              )
            )}
            {runMode !== 'inspect' && agentRunning && runState !== 'WAITING_FOR_USER' && onPauseToggle && (
              <button
                type="button"
                onClick={onPauseToggle}
                className={`flex items-center gap-1.5 rounded-xl border px-2 sm:px-2.5 py-1 text-[11px] font-bold transition-all shrink-0 ${
                  paused
                    ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25'
                    : 'border-white/[0.08] bg-white/[0.04] text-slate-200 hover:bg-white/[0.08]'
                }`}
                title={paused ? 'Resume the agent' : 'Pause the agent at the next safe point'}
              >
                {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
                <span>{paused ? 'Resume' : 'Pause'}</span>
              </button>
            )}
            {(active || live) && (
              <button
                type="button"
                onClick={onStop}
                className="flex items-center gap-1 px-2.5 sm:px-3 py-1 rounded-xl bg-red-500/20 hover:bg-red-500/30 text-red-400 border border-red-500/40 text-[11px] sm:text-xs font-bold transition-all shrink-0"
                title={active ? 'Stop the application and close the browser' : 'Close the live browser'}
              >
                <Power className="w-3.5 h-3.5" />
                <span>{active ? 'Stop' : 'Close'}</span>
              </button>
            )}
            <button
              type="button"
              onClick={() => setIsFullscreen(!isFullscreen)}
              className="p-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-slate-300 border border-white/[0.08] transition-colors shrink-0"
              title={isFullscreen ? 'Exit full screen' : 'Expand view'}
            >
              {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
            </button>
          </div>
        </div>

        {live && (
          <div className="flex items-center gap-1.5 mt-2">
            <button
              type="button"
              onClick={() => navigate('back')}
              disabled={!canControl}
              className="p-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-slate-300 border border-white/[0.08] disabled:opacity-30 transition-all"
              title="Back"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => navigate('forward')}
              disabled={!canControl}
              className="p-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-slate-300 border border-white/[0.08] disabled:opacity-30 transition-all"
              title="Forward"
            >
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => navigate('reload')}
              disabled={!canControl}
              className="p-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-slate-300 border border-white/[0.08] disabled:opacity-30 transition-all"
              title="Reload"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
            <form onSubmit={submitAddress} className="flex-1 min-w-0">
              <div className="relative">
                <Globe2 className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  value={address}
                  onChange={(event) => {
                    addressEditingRef.current = true;
                    setAddress(event.target.value);
                  }}
                  onFocus={() => {
                    addressEditingRef.current = true;
                  }}
                  onBlur={() => {
                    addressEditingRef.current = false;
                    if (!address.trim()) setAddress(pageInfo.url || '');
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Escape') {
                      addressEditingRef.current = false;
                      setAddress(pageInfo.url || '');
                      event.currentTarget.blur();
                    }
                  }}
                  disabled={!canControl}
                  spellCheck={false}
                  className="w-full pl-8 pr-3 py-1.5 rounded-md bg-slate-900 border border-slate-800 focus:border-amber-500/70 text-[11px] font-mono text-slate-300 outline-none disabled:opacity-60"
                  placeholder="https://official-portal.gov.in/apply"
                  title={pageInfo.title || displayUrl(pageInfo.url) || 'Live page address'}
                />
              </div>
            </form>
            <span
              className={`flex items-center gap-1 text-[10px] font-mono px-1.5 sm:px-2 py-1 rounded-md border shrink-0 ${
                canControl
                  ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30'
                  : 'text-amber-300 bg-amber-500/10 border-amber-500/30'
              }`}
              title={control.reason}
            >
              {canControl || takeover?.active ? <MousePointer2 className="w-3 h-3" /> : <Shield className="w-3 h-3" />}
              <span className="hidden sm:inline">
                {takeover?.active
                  ? 'You have control'
                  : canControl
                    ? 'You can click and type'
                    : 'Agent has control'}
              </span>
            </span>
          </div>
        )}

        {live && canControl && (
          <div className="mt-2 flex items-center gap-1.5 lg:hidden">
            <input
              value={typing}
              onChange={(event) => forwardTyping(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  pressKey('Enter');
                  setTyping('');
                }
              }}
              placeholder="Tap a field, then type here…"
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
              className="min-h-[40px] min-w-0 flex-1 rounded-xl border border-slate-800 bg-slate-900 px-3 text-slate-200 outline-none focus:border-amber-500/70"
            />
            <button
              type="button"
              onClick={() => {
                pressKey('Tab');
                setTyping('');
              }}
              className="min-h-[40px] rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 text-[11px] font-bold text-slate-300"
            >
              Next
            </button>
            <button
              type="button"
              onClick={() => {
                pressKey('Backspace');
                setTyping((value) => value.slice(0, -1));
              }}
              className="min-h-[40px] rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 text-[11px] font-bold text-slate-300"
            >
              ⌫
            </button>
          </div>
        )}
      </div>

      {/* Real page, streamed over CDP and forwarding input */}
      <div
        ref={shellRef}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        onKeyUp={handleKeyUp}
        onPaste={handlePaste}
        onMouseDown={(event) => {
          if (fromTouch()) return;
          shellRef.current?.focus();
          sendMouse(event, 'down');
        }}
        onMouseUp={(event) => {
          if (fromTouch()) return;
          sendMouse(event, 'up');
        }}
        onMouseMove={(event) => {
          if (fromTouch()) return;
          handleMouseMove(event);
        }}
        onContextMenu={(event) => event.preventDefault()}
        style={{ touchAction: 'pan-y' }}
        className={`relative flex-1 bg-slate-950 overflow-auto p-2 outline-none ${
          canControl ? 'cursor-crosshair' : 'cursor-default'
        }`}
      >
        {imageSource ? (
          <div
            className="relative mx-auto transition-[width] duration-200"
            style={{ width: `${zoom}%` }}
          >
            <img
              ref={imageRef}
              src={imageSource}
              alt="Live interactive view of the portal"
              draggable={false}
              className="w-full h-auto rounded-lg border border-slate-800 shadow-2xl select-none"
            />
            {showSom && somMarks.map((m) => {
              const leftPct = (m.rect.x / (viewport.width || 1280)) * 100;
              const topPct = (m.rect.y / (viewport.height || 800)) * 100;
              const widthPct = (m.rect.width / (viewport.width || 1280)) * 100;
              const heightPct = (m.rect.height / (viewport.height || 800)) * 100;
              return (
                <div
                  key={m.index}
                  className="absolute border border-cyan-400 bg-cyan-500/15 pointer-events-none rounded transition-all z-10"
                  style={{
                    left: `${leftPct}%`,
                    top: `${topPct}%`,
                    width: `${widthPct}%`,
                    height: `${heightPct}%`,
                  }}
                >
                  <span className="absolute -top-3.5 -left-1 px-1 py-0.2 bg-cyan-400 text-slate-950 font-mono font-extrabold text-[9px] rounded shadow-md">
                    {m.index}
                  </span>
                </div>
              );
            })}
            {somMessage && (
              <div className="absolute bottom-3 left-3 z-20 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-950/95 border border-cyan-500/50 text-cyan-300 text-[11px] font-mono shadow-xl backdrop-blur-md animate-fadeIn">
                <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse shrink-0" />
                <span>{somMessage}</span>
                <button
                  type="button"
                  onClick={() => setSomMessage('')}
                  className="ml-2 text-slate-400 hover:text-slate-200"
                >
                  ✕
                </button>
              </div>
            )}
            {(paused || takeover?.active) && (
              <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-slate-950/90 px-2.5 py-1 text-[10px] font-bold text-amber-300">
                <Pause className="h-3 w-3" />
                {takeover?.active ? 'You have the browser · FormPilot paused' : 'Paused by you'}
              </div>
            )}
            {!connected && live && (
              <div className="absolute top-3 right-3 flex items-center gap-1.5 text-[11px] font-mono px-2 py-1 rounded-md bg-slate-950/90 border border-amber-500/40 text-amber-300">
                <Unplug className="w-3.5 h-3.5" />
                <span>Reconnecting to the live page…</span>
              </div>
            )}
            {active && !paused && !takeover?.active && (
              <div className="absolute inset-0 pointer-events-none overflow-hidden rounded-lg">
                <div className="w-full h-1 bg-gradient-to-r from-transparent via-amber-400/50 to-transparent animate-scanline opacity-75" />
              </div>
            )}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center p-6 sm:p-8">
            <div className="w-full max-w-lg text-center animate-fadeIn">
              {/* Emblem */}
              <div className="relative mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-900 to-slate-950 text-amber-400 shadow-xl shadow-amber-500/5">
                <Globe2 className="h-8 w-8 text-amber-400/90" />
                <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center">
                  <span className="h-2 w-2 rounded-full bg-emerald-400 animate-ping" />
                  <span className="absolute h-2 w-2 rounded-full bg-emerald-400" />
                </span>
              </div>

              <h3 className="text-base sm:text-lg font-extrabold text-white tracking-tight">
                {finished ? 'Application Session Concluded' : 'Interactive Browser Cockpit Ready'}
              </h3>
              <p className="mx-auto mt-2 max-w-sm text-xs leading-relaxed text-slate-400">
                {finished
                  ? 'The live session was safely closed. No payment or final submission was made without your explicit review. Start a new session whenever you are ready.'
                  : 'FormPilot streams a live headless Chromium instance. Enter any official portal or launch our safe practice recruitment sandbox below.'}
              </p>

              {onPractice && (
                <div className="mt-6 flex flex-col items-center">
                  <button
                    type="button"
                    onClick={onPractice}
                    className="inline-flex items-center gap-2.5 rounded-xl border border-amber-500/50 bg-gradient-to-r from-amber-500/20 via-orange-500/15 to-amber-500/20 px-5 py-2.5 text-xs sm:text-sm font-extrabold text-amber-200 shadow-lg shadow-amber-500/10 transition-all hover:border-amber-400 hover:from-amber-500/30 hover:to-orange-500/25 active:scale-95"
                  >
                    <Play className="h-4 w-4 fill-current text-amber-400" />
                    <span>Launch Practice Recruitment Portal</span>
                  </button>
                  <span className="mt-1.5 text-[10px] text-slate-500">
                    Safe mock environment with demo OTP &amp; OTR registration
                  </span>
                </div>
              )}

              {/* 3 Value Pillars */}
              <div className="mt-7 grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-left">
                <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 p-3 transition-colors hover:border-slate-700">
                  <div className="flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-sky-500/10 text-sky-400">
                      <Globe2 className="h-3.5 w-3.5" />
                    </span>
                    <div className="text-[11px] font-bold text-slate-200">Real Browser</div>
                  </div>
                  <div className="mt-1 text-[10px] leading-relaxed text-slate-400">
                    Live screencast of official portals directly inside your assistant.
                  </div>
                </div>

                <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 p-3 transition-colors hover:border-slate-700">
                  <div className="flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-amber-500/10 text-amber-400">
                      <Sparkles className="h-3.5 w-3.5" />
                    </span>
                    <div className="text-[11px] font-bold text-slate-200">Profile-Aware</div>
                  </div>
                  <div className="mt-1 text-[10px] leading-relaxed text-slate-400">
                    Fills matching personal and educational records from your vault.
                  </div>
                </div>

                <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 p-3 transition-colors hover:border-slate-700">
                  <div className="flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400">
                      <ShieldCheck className="h-3.5 w-3.5" />
                    </span>
                    <div className="text-[11px] font-bold text-slate-200">Zero Auto-Pay</div>
                  </div>
                  <div className="mt-1 text-[10px] leading-relaxed text-slate-400">
                    Payment, OTP, and final submission gates always stay in your control.
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {inputError && (
          <div className="sticky bottom-2 left-2 right-2 z-10 mx-auto max-w-lg rounded-xl bg-red-950/95 border border-red-500/50 px-3 py-2 text-[11px] text-red-200 shadow-xl">
            {inputError}
          </div>
        )}

        {pendingGate && (
          <button
            type="button"
            onClick={onOpenGate}
            className="absolute bottom-3 right-3 z-10 flex items-center gap-2 rounded-xl bg-amber-500 hover:bg-amber-400 px-4 py-2.5 text-xs font-extrabold text-slate-950 shadow-xl"
          >
            <Shield className="w-4 h-4" />
            <span>Checkpoint needs you</span>
          </button>
        )}
      </div>

      {/* Status footer */}
      <div className="bg-slate-950/80 px-3 sm:px-4 py-1.5 sm:py-2 border-t border-slate-800/80 text-[10px] sm:text-[11px] text-slate-500 flex items-center justify-between gap-2 font-mono shrink-0">
        <div className="flex items-center gap-2 sm:gap-3 min-w-0">
          <span className="flex items-center gap-1.5 shrink-0">
            {connected ? <Wifi className="w-3.5 h-3.5 text-emerald-400" /> : <Unplug className="w-3.5 h-3.5 text-slate-500" />}
            <span className="hidden sm:inline">
              {connected ? 'live page stream' : live ? 'disconnected' : finished ? 'session closed' : 'viewer only'}
            </span>
          </span>
          <span className="hidden sm:inline">•</span>
          <span className="truncate max-w-[140px] sm:max-w-xs" title={pageInfo.url || ''}>
            {displayUrl(pageInfo.url) || (runMode === 'inspect' ? 'Inspect-only browser' : 'Waiting for a portal')}
          </span>
          {frameCount > 0 && (
            <>
              <span className="hidden md:inline">•</span>
              <span className="hidden md:inline">{frameCount.toLocaleString()} frames</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          {imageSource && (
            <div className="flex items-center gap-0.5 rounded-md border border-slate-800 bg-slate-900 p-0.5">
              <button
                type="button"
                onClick={() => setZoom((value) => Math.max(50, value - 25))}
                disabled={zoom <= 50}
                className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200 disabled:opacity-30"
                title="Zoom out"
              >
                <ZoomOut className="h-3 w-3" />
              </button>
              <button
                type="button"
                onClick={() => setZoom(100)}
                className="min-w-[34px] sm:min-w-[38px] rounded px-1 text-[9px] sm:text-[10px] font-bold text-slate-400 hover:text-slate-200"
                title="Reset zoom"
              >
                {zoom}%
              </button>
              <button
                type="button"
                onClick={() => setZoom((value) => Math.min(200, value + 25))}
                disabled={zoom >= 200}
                className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200 disabled:opacity-30"
                title="Zoom in"
              >
                <ZoomIn className="h-3 w-3" />
              </button>
            </div>
          )}
          {!canControl && !takeover?.active && live && (
            <button
              type="button"
              onClick={takeover?.available ? onTakeover : requestControl}
              className="text-[10px] font-bold text-amber-300 hover:text-amber-200 underline decoration-dotted"
              title={takeover?.available ? 'Pause FormPilot and control the page' : control.reason}
            >
              Takeover
            </button>
          )}
          <span className="hidden sm:flex items-center gap-1.5 text-slate-400">
            <Shield className="w-3.5 h-3.5 text-amber-500" />
            <span>Never auto-pays</span>
          </span>
        </div>
      </div>
    </div>
  );
}
