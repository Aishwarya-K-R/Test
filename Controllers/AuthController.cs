using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Patient_Management_System.Models;
using Patient_Management_System.Services;

namespace Patient_Management_System.Controllers
{
    [ApiController]
    [Route("auth/")]
    public class AuthController(AuthService authService): ControllerBase
    {
        AuthService _authService = authService;

        [HttpPost("signup")]
        public async Task<ActionResult> Signup(User user)
        {
            if(!ModelState.IsValid)
            {
                return BadRequest(ModelState);
            }
            await _authService.Signup(user);
            return Ok("User registered successfully!!!");
        }

        [EnableRateLimiting("loginLimiter")]
        [HttpPost("login")]
        public async Task<ActionResult> Login(User user)
        {
            if(!ModelState.IsValid)
            {
                return BadRequest(ModelState);
            }

            var token = await _authService.Login(user);
            if(token == null)
            {
                return Unauthorized("Invalid token!!!");
            }
            return Ok("Login successful !!! Token: " + token);
        }
    }
}
