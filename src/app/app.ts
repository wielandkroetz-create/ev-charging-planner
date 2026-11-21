import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { BaseChartDirective } from 'ng2-charts';

import {
  Chart,
  registerables,
  ChartConfiguration
} from 'chart.js';

import { PlannerService } from './services/planner.service';

Chart.register(...registerables);

@Component({
  selector: 'app-root',
  imports: [
    FormsModule,
    BaseChartDirective
  ],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {

  protected readonly title = signal('ev-charging-planner');

  planner = inject(PlannerService);

  prices: any[] = [];

  selectedSlots: number[] = [];

  optimizationResult: any = null;

  energyKwh = 35;

  chargingPowerKw = 11;

  providerMarkupCt = 2.5;

  optimizationMethod = 'lowest-cost';

  departureTime = '07:00';

  maxInterruptions = 1;

  chartData: ChartConfiguration<'line'>['data'] = {
    labels: [],
    datasets: []
  };

  chartOptions: ChartConfiguration<'line'>['options'] = {

    responsive: true,

    maintainAspectRatio: false,

    plugins: {
      legend: {
        display: true
      }
    },

    scales: {

      x: {
        ticks: {
          maxTicksLimit: 12
        }
      },

      y: {

        beginAtZero: true,

        title: {
          display: true,
          text: 'ct/kWh'
        }
      }
    }
  };

  constructor() {
    this.loadPrices();
  }

  updateChart() {

    const labels = this.prices.map(
      (p: any) => p.time
    );

    const prices = this.prices.map(
      (p: any) => p.priceCt
    );

    const chargingOverlay = this.prices.map(
      (p: any) =>
        this.selectedSlots.includes(p.slot)
          ? p.priceCt
          : null
    );

    this.chartData = {

      labels,

      datasets: [

        {
          label: 'Day Ahead Price',

          data: prices,

          borderColor: '#0078d4',

          backgroundColor:
            'rgba(0,120,212,0.15)',

          fill: true,

          tension: 0.25,

          pointRadius: 0,

          borderWidth: 2
        },

        {
          label: 'Charging Window',

          data: chargingOverlay,

          borderColor: '#28a745',

          backgroundColor:
            'rgba(40,167,69,0.3)',

          fill: false,

          tension: 0.25,

          spanGaps: false,

          pointRadius: 0,

          borderWidth: 6
        }

      ]
    };
  }

  loadPrices() {

    this.planner.getPrices().subscribe({

      next: (response: any) => {

        this.prices = response.prices;

        this.updateChart();

      },

      error: (error) => {

        console.error(error);

      }

    });

  }

  optimize() {

    const payload = {

      energyKwh: this.energyKwh,

      chargingPowerKw: this.chargingPowerKw,

      providerMarkupCt: this.providerMarkupCt,

      optimizationMethod: this.optimizationMethod,

      departureTime: this.departureTime,

      maxInterruptions: this.maxInterruptions

    };

    this.planner.optimize(payload).subscribe({

      next: (response: any) => {

        this.optimizationResult = response;

        this.selectedSlots = [];

        if (response.selectedSlots) {

          this.selectedSlots =
            response.selectedSlots.map(
              (slot: any) => slot.slot
            );

        }

        this.updateChart();

      },

      error: (error) => {

        console.error(error);

      }
    });

  }

}