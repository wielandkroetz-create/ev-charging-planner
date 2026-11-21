import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';

@Injectable({
  providedIn: 'root'
})
export class PlannerService {

  private http = inject(HttpClient);

  private apiUrl = 'http://localhost:8000';

  getPrices() {
    return this.http.get(
      `${this.apiUrl}/api/dayahead`
    );
  }

  optimize(payload: any) {
    return this.http.post(
      `${this.apiUrl}/api/optimize`,
      payload
    );
  }
}