import { create } from "zustand";
import type { Flight } from "../types";

export interface BookingState {
  // Selected flight from the search results
  flight:         Flight | null;
  // Seats the user has clicked on e.g. ["3A","3B"]
  selectedSeats:  string[];
  // How many passengers they searched for
  passengerCount: number;

  // Actions
  selectFlight:   (f: Flight, pax: number) => void;
  toggleSeat:     (seat: string) => void;
  clearBooking:   () => void;
}

export const useBookingStore = create<BookingState>((set, get) => ({
  flight:         null,
  selectedSeats:  [],
  passengerCount: 1,

  selectFlight: (flight, pax) =>
    set({ flight, passengerCount: pax, selectedSeats: [] }),

  toggleSeat: (seat) => {
    const { selectedSeats, passengerCount } = get();
    if (selectedSeats.includes(seat)) {
      // Deselect
      set({ selectedSeats: selectedSeats.filter((s) => s !== seat) });
    } else if (selectedSeats.length < passengerCount) {
      // Select only up to passengerCount
      set({ selectedSeats: [...selectedSeats, seat] });
    }
  },

  clearBooking: () =>
    set({ flight: null, selectedSeats: [], passengerCount: 1 }),
}));
