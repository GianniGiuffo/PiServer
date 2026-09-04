package dev.jellyfin.phonerelay.diagnostics

import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicReference

class RelayStateStore {
    private val current = AtomicReference(RelaySnapshot())
    private val listeners = CopyOnWriteArrayList<(RelaySnapshot) -> Unit>()

    fun snapshot(): RelaySnapshot = current.get()

    fun update(transform: (RelaySnapshot) -> RelaySnapshot) {
        while (true) {
            val previous = current.get()
            val next = transform(previous)
            if (current.compareAndSet(previous, next)) {
                listeners.forEach { it(next) }
                return
            }
        }
    }

    fun addListener(listener: (RelaySnapshot) -> Unit) {
        listeners += listener
        listener(current.get())
    }

    fun removeListener(listener: (RelaySnapshot) -> Unit) {
        listeners -= listener
    }
}
